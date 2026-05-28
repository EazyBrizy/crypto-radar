output "namespace" {
  value = kubernetes_namespace.crypto_radar.metadata[0].name
}
