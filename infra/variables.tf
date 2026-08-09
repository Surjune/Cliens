variable "aws_region" {
  description = "Region to deploy into. ap-south-1 (Mumbai) is closest to the users and to the districts this scores."
  type        = string
  default     = "ap-south-1"
}

variable "environment" {
  description = "Environment tag, and the value passed to the app's own ENVIRONMENT setting."
  type        = string
  default     = "production"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type.

    t4g.small (ARM, 2 GB) is the recommendation: scikit-learn plus the loaded
    model plus Postgres in a sibling container does not fit comfortably in the
    1 GB of a t4g.micro, and the model is unpickled into memory at startup.
    Graviton is roughly 20% cheaper than the x86 equivalent, and the image builds
    for arm64 without changes.
  EOT
  type        = string
  default     = "t4g.small"

  validation {
    condition     = can(regex("^(t4g|t3|t3a|m7g|m6i)\\.", var.instance_type))
    error_message = "Use a t4g/t3/t3a/m7g/m6i instance type; the AMI lookup keys off the family."
  }
}

variable "root_volume_gb" {
  description = <<-EOT
    Root volume size in GB.

    20 GB covers the OS, the container images (the backend image is ~700 MB with
    scikit-learn and its dependencies), and Postgres data. The database itself
    stays tiny — sites are a polygon and a few numbers each.
  EOT
  type        = number
  default     = 20
}

variable "public_host" {
  description = <<-EOT
    The hostname Caddy serves on.

    A domain you control (app.example.com) makes Caddy obtain a Let's Encrypt
    certificate automatically. Leave as ":80" to serve plain HTTP on the Elastic
    IP — fine for a demo, but the browser will not treat it as a secure context.
  EOT
  type        = string
  default     = ":80"
}

variable "allowed_ssh_cidrs" {
  description = <<-EOT
    CIDRs permitted to reach port 22.

    Empty by default, and it should stay empty: the instance has an SSM role, so
    `aws ssm start-session` gives a shell with no open SSH port and no key to
    lose. This exists only for the case where SSM is unavailable.
  EOT
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Application secrets
#
# Marked sensitive so Terraform will not print them in plan output or logs. They
# are stored in SSM Parameter Store as SecureString and pulled onto the instance
# at boot, so they never appear in the launch template's user data either — user
# data is readable by anything that can reach the instance metadata service.
# ---------------------------------------------------------------------------
variable "postgres_password" {
  description = "Password for the application's Postgres user. Generate a long random one."
  type        = string
  sensitive   = true
}

variable "sarvam_api_key_primary" {
  description = "Sarvam AI key used first for Tamil narration. Optional: without it the Listen buttons simply do not appear."
  type        = string
  sensitive   = true
  default     = ""
}

variable "sarvam_api_key_secondary" {
  description = "Second Sarvam key, used automatically once the first reports a rate or quota limit."
  type        = string
  sensitive   = true
  default     = ""
}

variable "mapbox_access_token" {
  description = "Optional. Raises the satellite imagery ceiling from zoom 19 to 22. Metered — the only paid service in the app."
  type        = string
  sensitive   = true
  default     = ""
}
