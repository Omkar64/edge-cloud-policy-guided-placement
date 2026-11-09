variable "aws_region" {
  description = "AWS region for the short-lived research cluster."
  type        = string
}

variable "cluster_name" {
  description = "Unique name for this EKS cluster."
  type        = string
  default     = "pac-phase2-lab"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes minor version. Change to a version currently offered in the chosen region."
  type        = string
  default     = "1.36"
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the experiment VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zones" {
  description = "Two AZ names in aws_region, in the same order as public_subnet_cidrs."
  type        = list(string)
  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Provide exactly two distinct Availability Zones."
  }
}

variable "public_subnet_cidrs" {
  description = "Two non-overlapping public subnet CIDRs, one per Availability Zone."
  type        = list(string)
  default     = ["10.40.0.0/20", "10.40.16.0/20"]
  validation {
    condition     = length(var.public_subnet_cidrs) == 2 && length(distinct(var.public_subnet_cidrs)) == 2
    error_message = "Provide exactly two distinct public subnet CIDRs."
  }
}

variable "cluster_api_allowed_cidrs" {
  description = "Public client CIDR allow-list for the EKS API; use your current public IPv4 /32."
  type        = list(string)
  validation {
    condition = length(var.cluster_api_allowed_cidrs) > 0 && alltrue([
      for cidr in var.cluster_api_allowed_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"
    ])
    error_message = "Restrict public Kubernetes API access to specific client CIDRs; 0.0.0.0/0 and ::/0 are forbidden."
  }
}

variable "capacity_type" {
  description = "Managed node group capacity. SPOT lowers EC2 cost but can be interrupted."
  type        = string
  default     = "SPOT"
  validation {
    condition     = contains(["SPOT", "ON_DEMAND"], var.capacity_type)
    error_message = "capacity_type must be SPOT or ON_DEMAND."
  }
}

variable "edge_instance_types" {
  description = "Compatible Spot pools for the emulated edge node group."
  type        = list(string)
  default     = ["t3.medium", "t3a.medium"]
  validation {
    condition     = length(var.edge_instance_types) > 0
    error_message = "At least one edge instance type is required."
  }
}

variable "cloud_instance_types" {
  description = "Compatible Spot pools for the emulated cloud node group."
  type        = list(string)
  default     = ["t3.medium", "t3a.medium"]
  validation {
    condition     = length(var.cloud_instance_types) > 0
    error_message = "At least one cloud instance type is required."
  }
}

variable "edge_desired_size" {
  description = "Desired worker count in the edge node group (0 to 2 for the bounded experiment)."
  type        = number
  default     = 1
  validation {
    condition     = var.edge_desired_size >= 0 && var.edge_desired_size <= 2
    error_message = "Keep edge_desired_size between 0 and 2 for the bounded experiment."
  }
}

variable "cloud_desired_size" {
  description = "Desired worker count in the cloud node group (0 to 2 for the bounded experiment)."
  type        = number
  default     = 1
  validation {
    condition     = var.cloud_desired_size >= 0 && var.cloud_desired_size <= 2
    error_message = "Keep cloud_desired_size between 0 and 2 for the bounded experiment."
  }
}

variable "edge_security_level" {
  description = "Experimental classification label for edge workers, not a security guarantee."
  type        = string
  default     = "high"
  validation {
    condition     = contains(["low", "medium", "high"], var.edge_security_level)
    error_message = "Security level must be low, medium, or high."
  }
}

variable "cloud_security_level" {
  description = "Experimental classification label for cloud workers, not a security guarantee."
  type        = string
  default     = "high"
  validation {
    condition     = contains(["low", "medium", "high"], var.cloud_security_level)
    error_message = "Security level must be low, medium, or high."
  }
}

variable "tags" {
  description = "Additional resource tags."
  type        = map(string)
  default     = {}
}
