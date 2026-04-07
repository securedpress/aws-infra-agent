# infra-agent

**AI-powered AWS infrastructure automation agent.**  
Accepts natural language commands → generates Terraform → provisions via GitHub Actions OIDC → monitors with CloudWatch → auto-remediates via Lambda.

Built on AWS Bedrock (Claude 4.6 Sonnet) · Terraform · GitHub Actions OIDC · Python

---

## What It Does

```
"spin up an ECS Fargate service with RDS PostgreSQL and CloudWatch alarms"
         ↓
infra-agent parses intent via AWS Bedrock
         ↓
Terraform plan generated and committed
         ↓
GitHub Actions OIDC applies plan to AWS (no long-lived credentials)
         ↓
CloudWatch monitors deployed resources
         ↓
Lambda auto-remediates on alarm (scale, restart, alert)
```

---

## Architecture

![infra-agent architecture](docs/architecture.png)

| Component | Technology |
|---|---|
| AI / NLP | AWS Bedrock — Claude 4.6 Sonnet |
| IaC | Terraform 1.7+ |
| CI/CD | GitHub Actions with OIDC (no stored AWS keys) |
| Compute | ECS Fargate |
| Database | RDS PostgreSQL (blue/green capable) |
| Secrets | AWS Secrets Manager |
| Monitoring | CloudWatch Alarms + EventBridge |
| Auto-remediation | Lambda (Python 3.12) |

---

## Quick Start

### Prerequisites

- AWS account with Bedrock Claude 4.6 Sonnet enabled (us-east-1)
- Terraform 1.7+
- Python 3.12+
- GitHub repo with Actions enabled

### 1. Bootstrap OIDC trust

```bash
cd infra/
terraform init
terraform apply -var="github_org=your-org" -var="github_repo=infra-agent"
```

### 2. Install agent dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the agent

```bash
python -m agent.main \
  --prompt "deploy an ECS Fargate service for my API with RDS PostgreSQL" \
  --env staging \
  --region us-east-1
```

The agent will:
1. Parse your prompt via Bedrock
2. Generate a Terraform plan in `terraform/generated/`
3. Open a PR with the plan for review
4. Apply on merge via GitHub Actions

---

## Repository Structure

```
infra-agent/
├── agent/
│   ├── bedrock_client.py      # AWS Bedrock integration (Claude 4.6 Sonnet)
│   ├── intent_parser.py       # Natural language → structured intent
│   ├── terraform_generator.py # Intent → Terraform HCL
│   └── remediator.py          # Auto-remediation logic
├── .github/
│   └── workflows/
│       ├── provision.yml      # Triggered on PR merge — applies Terraform
│       └── remediate.yml      # Triggered by CloudWatch → EventBridge → Lambda
├── terraform/
│   ├── modules/
│   │   ├── ecs-fargate/       # Reusable ECS Fargate module
│   │   ├── rds-postgres/      # RDS PostgreSQL with blue/green
│   │   └── cloudwatch-alarms/ # Standardized alarm templates
│   └── generated/             # Agent-generated plans land here
├── lambda/
│   └── remediation_handler.py # Lambda — scales, restarts, alerts
├── tests/
│   └── test_intent_parser.py
└── requirements.txt
```

---

## How the Agent Works

### Provisioning Flow

```python
# 1. User provides natural language prompt
prompt = "deploy a Fargate API with Postgres, autoscaling 2-10 tasks"

# 2. Bedrock parses intent into structured config
intent = intent_parser.parse(prompt)
# → { service: "ecs-fargate", db: "rds-postgres", min_tasks: 2, max_tasks: 10 }

# 3. Terraform HCL generated from intent
tf_code = terraform_generator.generate(intent)

# 4. Committed to feature branch, PR opened
# 5. On merge → GitHub Actions OIDC applies via AssumeRoleWithWebIdentity
```

### Monitoring + Remediation Loop

```
CloudWatch Alarm (CPU > 80% for 5min)
    → EventBridge rule triggers
    → Lambda remediation_handler invoked
    → ECS service scaled up (desired_count += 2)
    → SNS notification sent
    → CloudWatch custom metric logged
```

---

## Security Design

- **No long-lived AWS credentials** — GitHub Actions uses OIDC AssumeRoleWithWebIdentity
- **Least-privilege IAM** — separate roles for provisioning vs remediation
- **Secrets Manager** — no secrets in environment variables or code
- **Terraform state** — S3 backend with DynamoDB locking, encrypted at rest
- **Agent scope** — Bedrock model cannot execute AWS actions directly; all changes go through reviewed Terraform PRs

---

## Terraform Modules

### `ecs-fargate`

```hcl
module "api_service" {
  source      = "./terraform/modules/ecs-fargate"
  service_name = "my-api"
  image        = "my-api:latest"
  cpu          = 512
  memory       = 1024
  min_tasks    = 2
  max_tasks    = 10
  environment  = "staging"
}
```

### `rds-postgres`

```hcl
module "database" {
  source         = "./terraform/modules/rds-postgres"
  identifier     = "my-api-db"
  instance_class = "db.t3.medium"
  engine_version = "15.4"
  multi_az       = true
  environment    = "staging"
}
```

---

## AWS Bedrock Setup

This project uses Claude 4.6 Sonnet via Amazon Bedrock in `us-east-1`.

Enable model access in the AWS Console:
```
Amazon Bedrock → Model access → Enable "Claude 4.6 Sonnet"
```

Required IAM permissions for the agent role:
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0"
}
```

---

## GitHub Actions OIDC Trust

No AWS access keys are stored in GitHub. The workflow uses OIDC to assume an IAM role:

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::${{ vars.AWS_ACCOUNT_ID }}:role/infra-agent-github-actions
    aws-region: us-east-1
```

The IAM trust policy restricts access to this specific repo and branch.

---

## Auto-Remediation Rules

| Alarm | Condition | Action |
|---|---|---|
| `ecs-cpu-high` | CPU > 80% for 5min | Scale out +2 tasks |
| `ecs-task-count-low` | Running tasks < desired | Force new deployment |
| `rds-connections-high` | Connections > 80% max | SNS alert + scale compute |
| `ecs-memory-high` | Memory > 85% for 5min | SNS alert + scale out |

---

## Related Work

- [sagemaker-autopilot-demo](https://github.com/securedpress/sagemaker-autopilot-demo) — ML pipeline on AWS
- [aws-iac-modules](https://github.com/securedpress/aws-iac-modules) — Production Terraform modules

---

## License

MIT — see [LICENSE](LICENSE)
