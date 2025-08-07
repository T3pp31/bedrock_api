import os
import json
import boto3
import base64
from typing import Dict, Any, List

# Bedrock クライアントを初期化
bedrock = boto3.client('bedrock-runtime')
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0")
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")

# サポートされるファイルタイプとその制限
SUPPORTED_IMAGE_TYPES = {
    'image/png': {'max_size': 3.75 * 1024 * 1024, 'extensions': ['.png']},
    'image/jpeg': {'max_size': 3.75 * 1024 * 1024, 'extensions': ['.jpg', '.jpeg']},
    'image/gif': {'max_size': 3.75 * 1024 * 1024, 'extensions': ['.gif']},
    'image/webp': {'max_size': 3.75 * 1024 * 1024, 'extensions': ['.webp']}
}

SUPPORTED_DOCUMENT_TYPES = {
    'application/pdf': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.pdf']},
    'text/csv': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.csv']},
    'application/msword': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.doc']},
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.docx']},
    'application/vnd.ms-excel': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.xls']},
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.xlsx']},
    'text/html': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.html']},
    'text/plain': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.txt']},
    'text/markdown': {'max_size': 4.5 * 1024 * 1024, 'extensions': ['.md']}
}

def validate_file(file_data: Dict[str, Any]) -> tuple[bool, str]:
    """
    ファイルの検証を行う
    Args:
        file_data: ファイルデータ（type, media_type, data, nameを含む）
    Returns:
        tuple: (検証成功フラグ, エラーメッセージ)
    """
    file_type = file_data.get('type')
    media_type = file_data.get('media_type', '')
    data = file_data.get('data', '')
    name = file_data.get('name', '')
    
    # Base64データのサイズチェック
    try:
        decoded_data = base64.b64decode(data)
        file_size = len(decoded_data)
    except:
        return False, "無効なBase64データです"
    
    # ファイルタイプに応じた検証
    if file_type == 'image':
        if media_type not in SUPPORTED_IMAGE_TYPES:
            return False, f"サポートされていない画像形式です: {media_type}"
        max_size = SUPPORTED_IMAGE_TYPES[media_type]['max_size']
        if file_size > max_size:
            return False, f"画像サイズが制限を超えています（最大3.75MB）"
    elif file_type == 'document':
        if media_type not in SUPPORTED_DOCUMENT_TYPES:
            return False, f"サポートされていないドキュメント形式です: {media_type}"
        max_size = SUPPORTED_DOCUMENT_TYPES[media_type]['max_size']
        if file_size > max_size:
            return False, f"ドキュメントサイズが制限を超えています（最大4.5MB）"
    else:
        return False, f"無効なファイルタイプです: {file_type}"
    
    return True, ""

def build_message_content(prompt: str, files: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    メッセージコンテンツを構築する
    Args:
        prompt: テキストプロンプト
        files: ファイルデータのリスト
    Returns:
        list: コンテンツリスト
    """
    content = []
    
    # テキストを追加
    if prompt:
        content.append({
            "type": "text",
            "text": prompt
        })
    
    # ファイルを追加
    if files:
        image_count = 0
        document_count = 0
        
        for file_data in files:
            file_type = file_data.get('type')
            
            # ファイル数の制限チェック
            if file_type == 'image':
                image_count += 1
                if image_count > 20:
                    raise ValueError("画像は最大20枚までです")
            elif file_type == 'document':
                document_count += 1
                if document_count > 5:
                    raise ValueError("ドキュメントは最大5ファイルまでです")
            
            # ファイルの検証
            is_valid, error_msg = validate_file(file_data)
            if not is_valid:
                raise ValueError(error_msg)
            
            # コンテンツを構築
            if file_type == 'image':
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": file_data.get('media_type'),
                        "data": file_data.get('data')
                    }
                })
            elif file_type == 'document':
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": file_data.get('media_type'),
                        "data": file_data.get('data')
                    }
                })
    
    # 少なくとも1つのテキストブロックが必要
    if not any(item['type'] == 'text' for item in content):
        content.insert(0, {
            "type": "text",
            "text": "以下のファイルを分析してください："
        })
    
    return content

def lambda_handler(event, context):
    """
    Lambda エントリポイント
    Args:
      event: API Gateway からのリクエスト情報 (JSON)
      context: Lambda 実行コンテキスト
    Returns:
      dict: API Gateway 形式のレスポンス
    """
    try:
        body = json.loads(event.get('body', '{}'))
        prompt = body.get('prompt', '')
        files = body.get('files', [])
        
        # プロンプトまたはファイルが必要
        if not prompt and not files:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "プロンプトまたはファイルが必要です"})
            }
        
        # 推論プロファイル ARN の検証
        if not (MODEL_ID.startswith('arn:aws') and 'inference-profile' in MODEL_ID):
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "環境変数 BEDROCK_MODEL_ID に推論プロファイル ARN を設定してください"})
            }
        
        # メッセージコンテンツを構築
        try:
            content = build_message_content(prompt, files)
        except ValueError as e:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": str(e)})
            }
        
        # Bedrock メッセージAPIを使用してチャットモデルを呼び出し
        messages = [
            {
                "role": "user",
                "content": content
            }
        ]
        
        payload = {
            "messages": messages,
            "max_tokens": 4000,  # マルチモーダルの場合は出力を増やす
            "anthropic_version": "bedrock-2023-05-31"
        }
        
        # Guardrailの有無に応じてパラメータを構築
        invoke_params = {
            "modelId": MODEL_ID,
            "contentType": 'application/json',
            "accept": 'application/json',
            "body": json.dumps(payload)
        }
        
        # Guardrailが設定されている場合はパラメータを追加
        if GUARDRAIL_ID:
            invoke_params["guardrailIdentifier"] = GUARDRAIL_ID
            invoke_params["guardrailVersion"] = GUARDRAIL_VERSION
        
        response = bedrock.invoke_model(**invoke_params)
        
    except Exception as e:
        # エラー内容を詳細に返す
        print("Bedrock API error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Bedrock API呼び出しでエラーが発生しました",
                "details": str(e)
            })
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
        content_list = result["content"]
        text_parts = []
        for item in content_list:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("text"):
                    text_parts.append(item.get("text"))
        assistantContent = " ".join(text_parts) if text_parts else None
    
    # デバッグ用ログ出力（CloudWatch Logs）
    print("Bedrock response structure:", list(result.keys()))
    if assistantContent is None:
        print("Assistant content is None. Full response:", result)
    
    return {
        "statusCode": 200,
        "body": json.dumps({"response": assistantContent})
    }