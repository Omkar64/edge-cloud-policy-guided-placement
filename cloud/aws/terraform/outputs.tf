output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.experiment.name
}

output "cluster_endpoint" {
  description = "Public EKS API endpoint; access is restricted by cluster_api_allowed_cidrs."
  value       = aws_eks_cluster.experiment.endpoint
}

output "region" {
  description = "AWS region used by the cluster."
  value       = var.aws_region
}

output "worker_node_groups" {
  description = "Managed node group names and labels for the emulated execution classes."
  value = {
    edge  = aws_eks_node_group.edge.node_group_name
    cloud = aws_eks_node_group.cloud.node_group_name
  }
}

output "kubeconfig_command" {
  description = "Run after apply to configure kubectl."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${var.cluster_name}"
}
