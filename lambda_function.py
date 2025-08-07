import os
import json
import boto3

# Bedrock クライアントを初期化
bedrock = boto3.client('bedrock-runtime')
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")  # モデルIDまたは推論プロファイルARN
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID")

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
    # Guardrail有効時はpayloadのトップレベルに"input"キーが必要
    if GUARDRAIL_ID:
        payload = {
            "input": {
                "messages": messages,
                "max_tokens": 1000,
                "anthropic_version": "bedrock-2023-05-31"
            }
        }
    else:
        payload = {
            "messages": messages,
            "max_tokens": 1000,
            "anthropic_version": "bedrock-2023-05-31"
        }
    try:
        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType='application/json',
            accept='application/json',
            guardrailIdentifier=GUARDRAIL_ID,
            body=json.dumps(payload)
        )
    except Exception as e:
        # エラー内容を詳細に返す
        print("Bedrock API error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Bedrock API呼び出しでエラーが発生しました。入力形式やGuardrailの設定を確認してください。", "details": str(e)})
        }
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
