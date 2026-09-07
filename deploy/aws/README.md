# AWS Fargate worker deployment preparation

These reusable templates prepare the worker image for ECS/Fargate. They do not
deploy the API or frontend, and the application never creates AWS infrastructure
during startup. Every command below is a manual, review-before-running operation.
Examples use `us-east-2` and a local profile named `fractal-route`; adapt both to
the target account.

## Architecture and cost boundary

The one-container Fargate service runs `python -m backend.worker`. It pulls a
Linux/x86-64 image from private ECR, long-polls the standard
`fractal-route-jobs` queue, downloads only `routes/*/original.gpx` from the
private route bucket, connects to RDS PostgreSQL, and writes stdout/stderr to
CloudWatch Logs. It has no listener, load balancer, inbound port, or autoscaling.

ECR image storage, log ingestion, RDS, public IPv4 addresses, and running Fargate
tasks can incur charges. Review current AWS pricing and account state before
running any provisioning command.

## Shell configuration

Start a new PowerShell session, authenticate with temporary credentials, and set
only identifiers—not secrets—in the environment:

```powershell
aws login --profile fractal-route --region us-east-2
$env:AWS_PROFILE = 'fractal-route'
$env:AWS_REGION = 'us-east-2'
$env:AWS_ACCOUNT_ID = aws sts get-caller-identity --profile $env:AWS_PROFILE --query Account --output text
$env:S3_BUCKET = 'YOUR_EXISTING_PRIVATE_BUCKET'
$env:SQS_QUEUE_URL = aws sqs get-queue-url --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-name fractal-route-jobs --query QueueUrl --output text
$env:ECR_REPOSITORY = 'fractal-route-worker'
$env:IMAGE_TAG = 'VERSION_OR_COMMIT'
$env:CLOUDWATCH_LOG_GROUP = '/fractal-route/worker'
```

Never set AWS access-key variables for ECS. Local `AWS_PROFILE` is intentionally
absent from the task definition; Fargate supplies temporary task-role credentials.

Record resolved identifiers only in the ignored
`deploy/aws/aws-resources.local.json`. Keep account-specific IDs there; committed
JSON templates use runtime placeholders.

## 1. ECR repository and image

The deployment expects a private `fractal-route-worker` repository. Verify the
selected repository without pushing:

```powershell
aws ecr describe-repositories --profile $env:AWS_PROFILE --region $env:AWS_REGION --repository-names $env:ECR_REPOSITORY
```

Build the repository's existing `Dockerfile` as Linux/x86-64, authenticate Docker
with a temporary ECR token, push an explicit tag, and print both tagged and
digest-addressed URIs:

```powershell
.\deploy\aws\push-worker-image.ps1 -ImageTag $env:IMAGE_TAG -RepositoryName $env:ECR_REPOSITORY -Region $env:AWS_REGION -Profile $env:AWS_PROFILE
```

The same image remains usable as the FastAPI container with its default command,
or as the worker by overriding the command to `python -m backend.worker`. It
contains Python and requirements, not `.venv`, `.env*`, GPX files, tests, or AWS
credentials; `.dockerignore` enforces those exclusions.

`botocore[crt]` is included for the local Python SDK path that consumes credentials
from an AWS CLI `aws login` profile. It does not make ECS depend on AWS login;
ECS uses the container credential provider supplied by the IAM task role.

## 2. IAM roles

Both role identities use `ecs-tasks-trust-policy.json`.

The worker role has the rendered `FractalRouteWorkerAccess` inline policy from
`worker-task-role-policy.json`. Its resolved resources are recorded only in the
ignored local deployment metadata, while the committed template retains
`${S3_BUCKET}`, `${AWS_REGION}`, and `${AWS_ACCOUNT_ID}` placeholders. Its only
permissions are:

- `s3:GetObject` for `${S3_BUCKET}/routes/*/original.gpx`
- `sqs:ReceiveMessage` and `sqs:DeleteMessage` for `fractal-route-jobs`

`GetQueueAttributes` and `ChangeMessageVisibility` are omitted because the current
worker never calls them.
Do not attach S3/SQS full-access or administrator policies.

`ecsTaskExecutionRole` already has the managed
`service-role/AmazonECSTaskExecutionRolePolicy`. That managed policy covers ECR
pulls and the `awslogs` driver. Render and attach
`execution-role-parameter-policy.json` has also been attached so the ECS agent can read only
`/fractal-route/database-url` with `ssm:GetParameters`. This role receives no
application S3/SQS access. Add `kms:Decrypt` only if the parameter uses a
customer-managed KMS key, restricted to that key.

To re-render the policy without modifying its source template:

```powershell
$renderedDirectory = Join-Path $env:TEMP 'fractal-route-deploy'
New-Item -ItemType Directory -Force -Path $renderedDirectory | Out-Null
$taskPolicy = (Get-Content deploy/aws/worker-task-role-policy.json -Raw).Replace('${S3_BUCKET}', $env:S3_BUCKET).Replace('${AWS_REGION}', $env:AWS_REGION).Replace('${AWS_ACCOUNT_ID}', $env:AWS_ACCOUNT_ID)
$taskPolicyPath = Join-Path $renderedDirectory 'worker-task-role-policy.json'
Set-Content -LiteralPath $taskPolicyPath -Value $taskPolicy -Encoding utf8
aws iam put-role-policy --profile $env:AWS_PROFILE --role-name fractal-route-worker-task-role --policy-name FractalRouteWorkerAccess --policy-document "file://$($taskPolicyPath.Replace('\', '/'))"

$executionPolicy = (Get-Content deploy/aws/execution-role-parameter-policy.json -Raw).Replace('${AWS_REGION}', $env:AWS_REGION).Replace('${AWS_ACCOUNT_ID}', $env:AWS_ACCOUNT_ID)
$executionPolicyPath = Join-Path $renderedDirectory 'execution-role-parameter-policy.json'
Set-Content -LiteralPath $executionPolicyPath -Value $executionPolicy -Encoding utf8
aws iam put-role-policy --profile $env:AWS_PROFILE --role-name ecsTaskExecutionRole --policy-name FractalRouteDatabaseParameter --policy-document "file://$($executionPolicyPath.Replace('\', '/'))"
```

## 3. SQS dead-letter queue

Create a standard DLQ in the same account and Region as the existing source queue,
then set `maxReceiveCount` to 5. This does not add an application retry loop;
retryable failures remain unacknowledged and SQS visibility/redelivery controls
the attempts.

```powershell
$env:DLQ_URL = aws sqs create-queue --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-name fractal-route-jobs-dlq --attributes MessageRetentionPeriod=1209600 --query QueueUrl --output text
$env:DLQ_ARN = aws sqs get-queue-attributes --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:DLQ_URL --attribute-names QueueArn --query Attributes.QueueArn --output text
$env:SOURCE_QUEUE_ARN = aws sqs get-queue-attributes --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:SQS_QUEUE_URL --attribute-names QueueArn --query Attributes.QueueArn --output text
$redriveAllowPolicy = @{ redrivePermission = 'byQueue'; sourceQueueArns = @($env:SOURCE_QUEUE_ARN) } | ConvertTo-Json -Compress
$dlqAttributes = @{ RedriveAllowPolicy = $redriveAllowPolicy } | ConvertTo-Json -Compress
$dlqAttributesPath = Join-Path $env:TEMP 'fractal-route-dlq-attributes.json'
Set-Content -LiteralPath $dlqAttributesPath -Value $dlqAttributes -Encoding utf8
aws sqs set-queue-attributes --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:DLQ_URL --attributes "file://$($dlqAttributesPath.Replace('\', '/'))"
$redrivePolicy = @{ deadLetterTargetArn = $env:DLQ_ARN; maxReceiveCount = '5' } | ConvertTo-Json -Compress
$queueAttributes = @{ RedrivePolicy = $redrivePolicy } | ConvertTo-Json -Compress
$queueAttributesPath = Join-Path $env:TEMP 'fractal-route-sqs-attributes.json'
Set-Content -LiteralPath $queueAttributesPath -Value $queueAttributes -Encoding utf8
aws sqs set-queue-attributes --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:SQS_QUEUE_URL --attributes "file://$($queueAttributesPath.Replace('\', '/'))"
```

Inspect queue counts and inspect one DLQ delivery without deleting it:

```powershell
aws sqs get-queue-attributes --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:DLQ_URL --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
aws sqs receive-message --profile $env:AWS_PROFILE --region $env:AWS_REGION --queue-url $env:DLQ_URL --max-number-of-messages 1 --visibility-timeout 30 --message-system-attribute-names ApproximateReceiveCount SentTimestamp
```

Receiving a message increments `ApproximateReceiveCount`; repeated console/API
inspection therefore affects it. After diagnosing and correcting the cause,
redrive back to the original source queue at a deliberately low rate:

```powershell
aws sqs start-message-move-task --profile $env:AWS_PROFILE --region $env:AWS_REGION --source-arn $env:DLQ_ARN --destination-arn $env:SOURCE_QUEUE_ARN --max-number-of-messages-per-second 1
```

## 4. RDS PostgreSQL and secure DATABASE_URL

The reviewed demo configuration is PostgreSQL `17.11`, `db.t4g.micro`, 20 GiB
`gp3`, encrypted storage, Single-AZ, one day of automated backup retention, no
storage autoscaling, no Performance Insights, no Enhanced Monitoring, and no log
exports. It uses the existing default VPC and the already-created
`fractal-route-rds-sg`. Do not place its endpoint, username, or password in source
control. The ECS task must not use `localhost`, `db`, or `host.docker.internal`.

No default DB subnet group currently exists. Review, then manually create one
from the three existing default-VPC subnets:

```powershell
$resources = Get-Content deploy/aws/aws-resources.local.json -Raw | ConvertFrom-Json
$env:RDS_SUBNET_GROUP = 'fractal-route-rds-subnets'
$env:RDS_SECURITY_GROUP_ID = $resources.network.rds_security_group_id
aws rds create-db-subnet-group --profile $env:AWS_PROFILE --region $env:AWS_REGION --db-subnet-group-name $env:RDS_SUBNET_GROUP --db-subnet-group-description 'Fractal Route RDS subnets' --subnet-ids $resources.network.public_subnet_ids --tags Key=Project,Value=FractalRoute
```

Set a strong password only in the current PowerShell process and review this
billable creation command before running it:

```powershell
$env:RDS_MASTER_PASSWORD = 'SET_A_STRONG_TEMPORARY_VALUE'
aws rds create-db-instance --profile $env:AWS_PROFILE --region $env:AWS_REGION --db-instance-identifier fractal-route-postgres --engine postgres --engine-version 17.11 --db-instance-class db.t4g.micro --allocated-storage 20 --storage-type gp3 --storage-encrypted --no-multi-az --no-publicly-accessible --vpc-security-group-ids $env:RDS_SECURITY_GROUP_ID --db-subnet-group-name $env:RDS_SUBNET_GROUP --port 5432 --db-name fractal_route --master-username fractal_route_admin --master-user-password $env:RDS_MASTER_PASSWORD --backup-retention-period 1 --auto-minor-version-upgrade --no-deletion-protection --no-enable-performance-insights --monitoring-interval 0 --copy-tags-to-snapshot --tags Key=Project,Value=FractalRoute
Remove-Item Env:RDS_MASTER_PASSWORD
```

Cost-affecting settings to review:

- `db.t4g.micro` is billed for every running instance hour; stopping RDS is
  temporary and AWS restarts a stopped instance after its service limit.
- Single-AZ avoids a second standby instance; enabling Multi-AZ increases cost.
- 20 GiB `gp3` is billed provisioned storage. No `--max-allocated-storage` means
  storage autoscaling cannot silently increase the allocation.
- Automated backups and manual snapshots can add backup-storage charges; delete
  retained snapshots when no longer required.
- Public IPv4 addressing can incur hourly charges. The recommended command keeps
  RDS private.
- Performance Insights, Enhanced Monitoring, and PostgreSQL log exports are
  disabled to avoid optional monitoring/log ingestion charges.
- Data transfer, additional IOPS/throughput, customer-managed KMS keys, and future
  PostgreSQL Extended Support can add charges. The command requests none of them.
- Deletion protection is disabled so an idle demo database can be removed; RDS
  continues billing until the instance is actually deleted.

Use the RDS endpoint in this existing application format:

```text
postgresql+psycopg://USER:PASSWORD@RDS_ENDPOINT:5432/fractal_route?sslmode=require
```

Create `/fractal-route/database-url` as a Parameter Store `SecureString`, preferably
through the console so the URL/password is not retained in shell history. The task
definition references its ARN under `secrets`; the plaintext value is not present
in JSON. If using PowerShell, place the URL only in a temporary process variable,
run `aws ssm put-parameter --type SecureString --name /fractal-route/database-url
--value $env:DATABASE_URL --overwrite`, then immediately remove the variable.

For a fresh private RDS database, initialize the schema later with a one-off ECS
task that overrides the container command to `python -m backend.schema_upgrade`.
That task incurs Fargate usage while it runs. If a local integration test is
required instead, temporarily enable public accessibility and temporarily add
the developer's current IPv4 `/32` to the RDS security group, run the command
below, then immediately revoke that rule and restore private accessibility:

```powershell
.\.venv\Scripts\python.exe -m backend.schema_upgrade
```

This creates the complete `routes` table and upgrades older tables with
`source_object_key`, `receive_count`, `queue_wait_ms`, `analysis_duration_ms`, and
`total_duration_ms`. It is intentionally a small development initializer, not a
home-grown migration framework.

## 5. Networking and security groups

- Put the worker in an existing/default VPC public subnet and set
  `assignPublicIp=ENABLED`. This demo configuration reaches ECR, S3, SQS,
  Parameter Store, and CloudWatch without a NAT Gateway.
- Give the worker security group **no inbound rules**. Normal outbound HTTPS plus
  PostgreSQL access is required.
- Give RDS a separate security group. Allow inbound TCP 5432 only from the worker
  security-group ID.
- Prefer private RDS subnet placement for normal ECS use.
- For the one-time local schema/integration test only, temporarily make RDS
  publicly accessible and add TCP 5432 from the developer's current public IPv4
  as a `/32`. Never use `0.0.0.0/0`. Remove that `/32` rule and disable public
  accessibility after the local test. Public IPv4 time can incur charges.

## 6. CloudWatch Logs

The empty demo log group already exists with seven-day retention. Verify it with:

```powershell
aws logs describe-log-groups --profile $env:AWS_PROFILE --region $env:AWS_REGION --log-group-name-prefix $env:CLOUDWATCH_LOG_GROUP
```

The task definition uses `awslogs` with stream prefix `ecs`. Each terminal worker
attempt emits a single-line JSON record with `route_id`, status, point count,
receive count, queue wait, analysis duration, and total duration. It never logs GPX
content, credentials, `DATABASE_URL`, or secret configuration.

Example inspection:

```powershell
aws logs tail $env:CLOUDWATCH_LOG_GROUP --profile $env:AWS_PROFILE --region $env:AWS_REGION --since 1h --follow
```

## 7. Render and register the task definition

The template fixes the Fargate shape at Linux/x86-64, `awsvpc`, 0.25 vCPU, and
512 MiB. Render identifiers into a temporary file, review it, then register it:

```powershell
$taskDefinition = (Get-Content deploy/aws/worker-task-definition.json -Raw).Replace('${AWS_ACCOUNT_ID}', $env:AWS_ACCOUNT_ID).Replace('${AWS_REGION}', $env:AWS_REGION).Replace('${ECR_REPOSITORY}', $env:ECR_REPOSITORY).Replace('${IMAGE_TAG}', $env:IMAGE_TAG).Replace('${S3_BUCKET}', $env:S3_BUCKET).Replace('${SQS_QUEUE_URL}', $env:SQS_QUEUE_URL).Replace('${CLOUDWATCH_LOG_GROUP}', $env:CLOUDWATCH_LOG_GROUP)
$taskDefinitionPath = Join-Path $renderedDirectory 'worker-task-definition.json'
Set-Content -LiteralPath $taskDefinitionPath -Value $taskDefinition -Encoding utf8
Get-Content -LiteralPath $taskDefinitionPath -Raw | ConvertFrom-Json | Out-Null
aws ecs register-task-definition --profile $env:AWS_PROFILE --region $env:AWS_REGION --cli-input-json "file://$($taskDefinitionPath.Replace('\', '/'))"
```

Before registering, replace the tagged `image` value with the immutable
digest-addressed URI printed by `push-worker-image.ps1` if strict byte-for-byte
deployment pinning is desired.

## 8. ECS cluster and one-worker service

After every preceding manual prerequisite is complete, create or update a
service using public subnet IDs and the no-inbound worker security group. The RDS
instance must be reachable from those subnets through its separate security
group. Inspect the account first to avoid creating a duplicate service.

```powershell
$resources = Get-Content deploy/aws/aws-resources.local.json -Raw | ConvertFrom-Json
$env:PUBLIC_SUBNET_IDS = $resources.network.public_subnet_ids -join ','
$env:WORKER_SECURITY_GROUP_ID = $resources.network.worker_security_group_id
$networkConfiguration = "awsvpcConfiguration={subnets=[$env:PUBLIC_SUBNET_IDS],securityGroups=[$env:WORKER_SECURITY_GROUP_ID],assignPublicIp=ENABLED}"
aws ecs create-service --profile $env:AWS_PROFILE --region $env:AWS_REGION --cluster fractal-route --service-name fractal-route-worker --task-definition fractal-route-worker --desired-count 1 --launch-type FARGATE --network-configuration $networkConfiguration
```

There is no load balancer or port mapping because the worker accepts no inbound
traffic. Verify the task, SQS drain, database state, and CloudWatch benchmark log.
Then stop compute charges while retaining the configuration:

```powershell
aws ecs update-service --profile $env:AWS_PROFILE --region $env:AWS_REGION --cluster fractal-route --service fractal-route-worker --desired-count 0
```

Local Compose remains unchanged: the local worker may continue using
`AWS_PROFILE=fractal-route`, while the ECS task uses its IAM task role and the
secure RDS `DATABASE_URL` injection.
