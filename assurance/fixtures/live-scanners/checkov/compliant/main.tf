resource "aws_s3_bucket" "private" {
  bucket = "tc-pipelines-live-scanner-compliant"
  acl    = "private"
}
