locals {
  common_tags = merge(var.tags, {
    Project   = "edge-cloud-pac"
    ManagedBy = "terraform"
    Phase     = "phase2-validation"
  })
  subnet_specs = {
    for index, cidr in var.public_subnet_cidrs : tostring(index) => {
      cidr = cidr
      az   = var.availability_zones[index]
    }
  }
}

resource "aws_vpc" "experiment" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${var.cluster_name}-vpc" })
}

resource "aws_internet_gateway" "experiment" {
  vpc_id = aws_vpc.experiment.id
  tags   = merge(local.common_tags, { Name = "${var.cluster_name}-igw" })
}

resource "aws_subnet" "public" {
  for_each = local.subnet_specs

  vpc_id                  = aws_vpc.experiment.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = true
  tags = merge(local.common_tags, {
    Name                                        = "${var.cluster_name}-public-${each.key}"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.experiment.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.experiment.id
  }
  tags = merge(local.common_tags, { Name = "${var.cluster_name}-public-rt" })
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_iam_role" "cluster" {
  name = "${var.cluster_name}-cluster"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "nodes" {
  name = "${var.cluster_name}-workers"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "worker_policies" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  ])
  role       = aws_iam_role.nodes.name
  policy_arn = each.value
}

resource "aws_eks_cluster" "experiment" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  vpc_config {
    subnet_ids              = [for subnet in aws_subnet.public : subnet.id]
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.cluster_api_allowed_cidrs
  }

  tags       = local.common_tags
  depends_on = [aws_iam_role_policy_attachment.cluster_policy]
}

resource "aws_eks_node_group" "edge" {
  cluster_name    = aws_eks_cluster.experiment.name
  node_group_name = "${var.cluster_name}-edge"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = [for subnet in aws_subnet.public : subnet.id]
  capacity_type   = var.capacity_type
  instance_types  = var.edge_instance_types
  disk_size       = 20

  scaling_config {
    min_size     = 0
    desired_size = var.edge_desired_size
    max_size     = 2
  }
  update_config { max_unavailable = 1 }
  labels = {
    "pac.io/node-type"      = "edge"
    "pac.io/security-level" = var.edge_security_level
  }
  tags       = merge(local.common_tags, { NodeClass = "edge" })
  depends_on = [aws_iam_role_policy_attachment.worker_policies]
}

resource "aws_eks_node_group" "cloud" {
  cluster_name    = aws_eks_cluster.experiment.name
  node_group_name = "${var.cluster_name}-cloud"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = [for subnet in aws_subnet.public : subnet.id]
  capacity_type   = var.capacity_type
  instance_types  = var.cloud_instance_types
  disk_size       = 20

  scaling_config {
    min_size     = 0
    desired_size = var.cloud_desired_size
    max_size     = 2
  }
  update_config { max_unavailable = 1 }
  labels = {
    "pac.io/node-type"      = "cloud"
    "pac.io/security-level" = var.cloud_security_level
  }
  tags       = merge(local.common_tags, { NodeClass = "cloud" })
  depends_on = [aws_iam_role_policy_attachment.worker_policies]
}
