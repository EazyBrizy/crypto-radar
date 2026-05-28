provider "kubernetes" {
  config_path = pathexpand("~/.kube/config")
}

provider "helm" {
  kubernetes {
    config_path = pathexpand("~/.kube/config")
  }
}

resource "kubernetes_namespace" "crypto_radar" {
  metadata {
    name = var.namespace
  }
}

resource "helm_release" "crypto_radar" {
  name       = "crypto-radar"
  namespace  = kubernetes_namespace.crypto_radar.metadata[0].name
  chart      = var.chart_path
  dependency_update = false
}
