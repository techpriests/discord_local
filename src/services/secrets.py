import boto3
from botocore.exceptions import ClientError
import json
import logging

logger = logging.getLogger(__name__)

class SecretsManager:
    def __init__(self, secret_name: str, region_name: str = "ap-northeast-2"):
        self.secret_name = secret_name
        self.region_name = region_name
        self.session = boto3.session.Session()
        self.client = self.session.client(
            service_name='secretsmanager',
            region_name=region_name
        )
    
    def get_secrets(self) -> dict:
        """Get secrets from AWS Secrets Manager"""
        try:
            get_secret_value_response = self.client.get_secret_value(
                SecretName=self.secret_name
            )
        except ClientError as e:
            logger.error(f"Error getting secret: {e}")
            raise e
        else:
            if 'SecretString' in get_secret_value_response:
                return json.loads(get_secret_value_response['SecretString'])
            raise ValueError("Secret not found in expected format") 