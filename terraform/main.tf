terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

#####################################################################
# Variables
#####################################################################
variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "function_name" {
  description = "Name of the lead-gen Lambda function"
  type        = string
  default     = "home-loan-lead-gen"
}

variable "lambda_zip_path" {
  description = "Path to the packaged Lambda deployment zip"
  type        = string
  default     = "../build/home-loan-lead-gen.zip"
}

variable "anthropic_api_key" {
  description = "Anthropic API key (scoring + outreach)"
  type        = string
  sensitive   = true
}

variable "batchdata_api_key" {
  description = "BatchData API key (property enrichment)"
  type        = string
  sensitive   = true
}

variable "census_api_key" {
  description = "US Census Bureau API key"
  type        = string
  sensitive   = true
}

variable "google_sheet_name" {
  description = "Name of the Google Sheet holding leads"
  type        = string
  default     = "Home Loan Leads"
}

variable "schedule_expression" {
  description = "EventBridge schedule (daily at 7am UTC)"
  type        = string
  default     = "cron(0 7 * * ? *)"
}

#####################################################################
# IAM role for the Lambda function
#####################################################################
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Basic execution: write logs to CloudWatch.
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

#####################################################################
# Outputs
#####################################################################
output "lambda_function_name" {
  value = aws_lambda_function.lead_gen.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.lead_gen.arn
}

output "schedule_rule" {
  value = aws_cloudwatch_event_rule.daily.name
}
