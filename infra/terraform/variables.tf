variable "namespace" {
  description = "Kubernetes namespace for Crypto Radar."
  type        = string
  default     = "crypto-radar"
}

variable "chart_path" {
  description = "Path to the local Crypto Radar Helm chart."
  type        = string
  default     = "../helm/crypto-radar"
}
