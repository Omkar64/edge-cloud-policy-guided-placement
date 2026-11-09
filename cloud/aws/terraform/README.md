# Phase 2 AWS/EKS infrastructure (Terraform)

This stack describes the Checkpoint 3 infrastructure only. Running `terraform init`, `fmt`, `validate`, or `plan` does not create AWS resources. **Do not run `terraform apply` without separate approval.**

## Scope and cost controls

The plan contains one VPC, one Internet Gateway, two public subnets in distinct AZs, one public route table and two subnet associations, one EKS control plane and its IAM role/policy attachment, one worker IAM role with three AWS-managed policy attachments, and two EKS managed node groups. Each group defaults to one Spot worker and supports a hard maximum of two, for up to four worker nodes. The four-node policy test uses two workers per group. EC2 instance types and desired counts are configurable. There is no NAT Gateway, load balancer, database, CloudWatch log group, or custom EBS volume resource.

These resources can incur charges: at the time this configuration was prepared (1 November 2026), AWS lists standard-support EKS clusters at **$0.10 per cluster-hour** and extended-support versions at **$0.60 per cluster-hour**. That is about $2.40/$14.40 per 24 hours for the control plane alone; worker EC2 Spot instances, their 20-GiB root EBS volumes, public IPv4 addresses, data transfer, and future add-ons are additional. See [current EKS pricing](https://aws.amazon.com/eks/pricing/). Kubernetes 1.36 is the configurable default and is currently under standard support; AWS lists its standard-support end date as 2 August 2027 and extended-support end date as 2 August 2028 in the [version lifecycle table](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html). Recheck region-specific instance availability and prices before applying. Spot is cheaper when capacity is available but may be interrupted; it can also fail to supply the requested capacity. An EKS cluster still has control-plane cost when worker counts are set to zero. Destroy promptly after the experiment.

To avoid a NAT Gateway, workers use public subnets with public IPv4 assignment and outbound routing through an Internet Gateway. The cluster enables **both** private and public Kubernetes API endpoints: kubelets inside the VPC use the private endpoint, while the public endpoint is restricted by a CIDR allow-list and rejects `0.0.0.0/0`. This distinction is required for nodes to join when the public allow-list contains only the operator’s workstation IP. AWS notes that public-only endpoint access requires node source CIDRs to be included, or private endpoint access to be enabled ([endpoint access](https://docs.aws.amazon.com/eks/latest/userguide/cluster-endpoint.html), [node join troubleshooting](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html)). Nodes still need outbound internet access for EKS bootstrap/image pulls, provided here by public IPv4 addresses and the Internet Gateway; no NAT Gateway is created. Never open worker security groups broadly, and do not treat public-subnet placement as private networking. EKS managed security groups control node ingress. The public endpoint CIDR must match the client network used for `kubectl`; if that IP changes, update and apply the CIDR change.

EKS requires cluster subnets in at least two AZs; AWS currently requires at least six available IP addresses per selected subnet and recommends 16 or more. See [EKS subnet requirements](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html). Workers use Spot capacity by default; AWS describes Spot interruptions and recommends multiple compatible instance types to improve capacity-pool availability ([managed node groups and Spot](https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html)).

## IAM

Terraform creates a cluster service role with `AmazonEKSClusterPolicy`, plus a worker role with `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly`, and `AmazonEKS_CNI_Policy`. The VPC CNI policy is attached to the shared worker role for the initial prototype; a later security pass can move it to a dedicated workload identity. The AWS identity running Terraform needs permission to create these listed resources and pass the two roles to EKS. The cluster-creator principal receives bootstrap cluster-admin access; do not share its credentials.

Do not store AWS keys in Terraform variables, tfvars, source, or container images. Use the standard AWS CLI profile/environment or an attached role. The cluster's edge/cloud labels describe emulated execution classes; they do not mean physical edge hardware. Security labels are experiment classifications only.

## Configure and validate

Copy the example file and set an actual AWS region, two AZ names in that region, and your current public client IP as a `/32`:

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars before use; 203.0.113.10/32 is documentation-only.
aws configure
```

Then:

```powershell
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -var-file=terraform.tfvars -out=phase2.tfplan
terraform show phase2.tfplan
```

Review the plan for exactly the resources described above and expected worker counts before separately approving any apply. The two node groups are Spot by default; for a controlled validation where interruptions would invalidate a run, choose `capacity_type = "ON_DEMAND"` and account for the higher compute cost.

After a separately approved apply, configure access and verify the labels:

```powershell
terraform apply phase2.tfplan
aws eks update-kubeconfig --region <region> --name <cluster-name>
kubectl get nodes --show-labels
```

## Cleanup

Capture experiment results first. Then review the destroy plan and run:

```powershell
terraform plan -destroy -var-file=terraform.tfvars -out=phase2-destroy.tfplan
terraform show phase2-destroy.tfplan
terraform destroy -var-file=terraform.tfvars
```

`terraform destroy` is deliberately not called by any project script. Confirm the cluster and its node groups are gone in the AWS console/CLI, and remove local Terraform state/plan files only after preserving any state required for recovery. Terraform state contains infrastructure metadata and should not be committed.
