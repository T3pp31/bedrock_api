# AWS Bedrock API 公開ガイド

## 概要

このリポジトリでは、AWS Bedrockを外部に公開するAPIを、Azure AD認証付きで構築する手順をまとめています。

## 1. Azure AD でアプリ登録・認証情報を用意する

1. Azureポータルで「アプリ登録」を開き、新規アプリを作成

2. 「認証」のページでリダイレクト URI は不要なのでスキップ

3. 「証明書とシークレット」でクライアントシークレットを発行

4. 以下の情報を控える
   - **TENANT_ID**: テナント ID

   - **CLIENT_ID**: アプリケーション (クライアント) ID

   - **CLIENT_SECRET**: クライアントシークレット

## 2. IAM ロールとポリシーの準備

### 信頼ポリシー (Lambda サービスへの信頼)

```json

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### アタッチするポリシー (Bedrock呼び出し & CloudWatchログ出力)

```json

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

- AWS 管理ポリシー `AWSLambdaBasicExecutionRole` を付与すると CloudWatch ログ権限は一括付与可能です

## 3. Lambda 関数 (Python) の実装例

ファイル名: `lambda_function.py`

```python

import os
import json
import boto3

# Bedrock クライアントを初期化
bedrock = boto3.client('bedrock-runtime')
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")  # モデルIDまたは推論プロファイルARN

def lambda_handler(event, context):
    """
    Lambda エントリポイント
    Args:
      event: API Gateway からのリクエスト情報 (JSON)
      context: Lambda 実行コンテキスト
    Returns:
      dict: API Gateway 形式のレスポンス
    """
    body = json.loads(event.get('body', '{}'))
    prompt = body.get('prompt', '')
    if not prompt:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "prompt is required"})
        }

    # 推論プロファイル ARN の検証（モデルIDではなく ARN を使用）
    if not (MODEL_ID.startswith('arn:aws') and 'inference-profile' in MODEL_ID):
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "環境変数 BEDROCK_MODEL_ID に推論プロファイル ARN を設定してください"})
        }
    # Bedrock メッセージAPIを使用してチャットモデルを呼び出し
    messages = [
        {"role": "user", "content": prompt}
    ]
    payload = {
        "messages": messages,
        # 最大トークン数のパラメータ名をAPIの期待する"max_tokens"に変更
        "max_tokens": 1000,
        # Anthropicモデル呼び出しに必要なバージョン指定
        "anthropic_version": "bedrock-2023-05-31"
    }
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        contentType='application/json',
        accept='application/json',
        body=json.dumps(payload)
    )
    # StreamingBodyから読み込んで文字列に変換しJSON解析
    raw_body = response['body'].read()
    body_str = raw_body.decode('utf-8')
    result = json.loads(body_str)
    # レスポンスからアシスタントのメッセージを取得（複数形式に対応）
    assistantContent = None
    if result.get("messages"):
        assistantContent = result["messages"][-1].get("content")
    elif result.get("completions"):
        firstCompletion = result["completions"][0]
        assistantContent = firstCompletion.get("message", {}).get("content") or firstCompletion.get("data", {}).get("content")
    elif result.get("completion"):
        assistantContent = result.get("completion")
    elif result.get("modelOutputs"):
        assistantContent = result["modelOutputs"][0].get("content")
    elif result.get("content"):
        # BedrockのメッセージAPIで返るcontent配列からテキスト抽出
        firstContent = result["content"][0]
        assistantContent = firstContent.get("text") or firstContent.get("content")
    # デバッグ用ログ出力（CloudWatch Logs）
    print("Bedrock response:", result)
    if assistantContent is None:
        print("Assistant content is None. Full response:", result)
    return {
        "statusCode": 200,
        "body": json.dumps({"response": assistantContent})
    }

```

## 4. API Gateway (HTTP API) + JWT オーソライザー設定

1. **HTTP API** を作成

2. 「認証」→「JWT オーソライザー」を追加
   - **Issuer**: `https://login.microsoftonline.com/{TENANT_ID}/v2.0`
   - **Audience**: Azure AD アプリの CLIENT_ID
3. 統合先に Lambda 関数 `InvokeBedrock` を紐付け
4. デプロイ (ステージ名: `prod`)

## 5. 動作確認

Azure AD から取得したアクセストークンを用いて cURL でリクエスト

```powershell

curl `
  -H "Authorization: Bearer <ACCESS_TOKEN>" `
  -H "Content-Type: application/json" `
  -d '{"prompt":"こんにちは"}' `
  https://<api-id>.execute-api.<region>.amazonaws.com/prod
```

## 6. 運用・監視・保守のポイント

- **CloudWatch Logs** でエラー・レイテンシを監視
- **CloudWatch Metrics** でアラームを設定
- シークレットは **AWS Secrets Manager** で安全に管理
- **AWS WAF** を組み合わせて攻撃対策を強化

## 7. 関連 Tips

- Bedrock のコスト監視は **AWS Cost Explorer** でアラート設定を
- JWT の公開鍵キャッシュ期限は適切に設定（例: 5 分）
- Lambda のプロビジョンド・コンカレンシーで Cold Start を緩和
