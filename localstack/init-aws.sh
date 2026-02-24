#!/bin/bash
# LocalStack bootstrap — creates S3 buckets + DynamoDB table
# Runs automatically via docker-compose healthcheck/entrypoint
set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="eu-west-2"

echo "⏳ Waiting for LocalStack to be ready…"
until aws --endpoint-url="$ENDPOINT" --region "$REGION" s3 ls 2>/dev/null; do
  sleep 1
done
echo "✅ LocalStack is ready"

# --- S3 buckets ---
echo "Creating S3 buckets…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  s3 mb s3://local-raw 2>/dev/null || true
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  s3 mb s3://local-derived 2>/dev/null || true

# --- DynamoDB table ---
echo "Creating DynamoDB table: MeetingsMetadata…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  dynamodb create-table \
    --table-name MeetingsMetadata \
    --attribute-definitions AttributeName=meeting_id,AttributeType=S \
    --key-schema AttributeName=meeting_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
  2>/dev/null || true

# --- V3 DynamoDB tables ---
echo "Creating DynamoDB table: QueryCache…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  dynamodb create-table \
    --table-name QueryCache \
    --attribute-definitions AttributeName=cache_id,AttributeType=S \
    --key-schema AttributeName=cache_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
  2>/dev/null || true

echo "Creating DynamoDB table: ChatHistory…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  dynamodb create-table \
    --table-name ChatHistory \
    --attribute-definitions AttributeName=session_id,AttributeType=S \
    --key-schema AttributeName=session_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
  2>/dev/null || true

echo "Creating DynamoDB table: UserMemory…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  dynamodb create-table \
    --table-name UserMemory \
    --attribute-definitions AttributeName=user_id,AttributeType=S \
    --key-schema AttributeName=user_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
  2>/dev/null || true

# Enable TTL on QueryCache table
echo "Enabling TTL on QueryCache…"
aws --endpoint-url="$ENDPOINT" --region "$REGION" \
  dynamodb update-time-to-live \
    --table-name QueryCache \
    --time-to-live-specification Enabled=true,AttributeName=ttl \
  2>/dev/null || true

echo "✅ LocalStack bootstrap complete"
aws --endpoint-url="$ENDPOINT" --region "$REGION" s3 ls
aws --endpoint-url="$ENDPOINT" --region "$REGION" dynamodb list-tables
