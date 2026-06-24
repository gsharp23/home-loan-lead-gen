#####################################################################
# Lambda function running the lead-gen pipeline
#####################################################################
resource "aws_cloudwatch_log_group" "lead_gen" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "lead_gen" {
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn
  runtime       = "python3.11"
  handler       = "agent.main.lambda_handler"

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  # The pipeline calls external APIs (Sheets, BatchData, Census, Claude) and
  # builds a vector index, so allow generous time and memory.
  timeout     = 300
  memory_size = 1024

  environment {
    variables = {
      ANTHROPIC_API_KEY = var.anthropic_api_key
      BATCHDATA_API_KEY = var.batchdata_api_key
      CENSUS_API_KEY    = var.census_api_key
      GOOGLE_SHEET_NAME = var.google_sheet_name
      # Lambda's writable filesystem is /tmp; keep the Chroma index there.
      CHROMA_DIR = "/tmp/chromadb"
    }
  }

  depends_on = [aws_cloudwatch_log_group.lead_gen]
}
