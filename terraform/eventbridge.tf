#####################################################################
# EventBridge schedule: invoke the Lambda daily at 7:00 AM UTC
#####################################################################
resource "aws_cloudwatch_event_rule" "daily" {
  name                = "${var.function_name}-daily"
  description         = "Trigger the home-loan lead-gen pipeline daily at 07:00 UTC"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.daily.name
  target_id = "${var.function_name}-target"
  arn       = aws_lambda_function.lead_gen.arn
}

# Allow EventBridge to invoke the Lambda function.
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lead_gen.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily.arn
}
