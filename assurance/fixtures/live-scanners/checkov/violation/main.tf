resource "aws_s3_bucket" "public" {
  bucket = "tc-pipelines-live-scanner-violation"
  acl    = "public-read"
}
