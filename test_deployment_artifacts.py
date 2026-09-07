import json
import unittest
from pathlib import Path


DEPLOYMENT_DIRECTORY = Path(__file__).parent / "deploy" / "aws"


def _load_json(filename: str) -> dict[str, object]:
    return json.loads((DEPLOYMENT_DIRECTORY / filename).read_text(encoding="utf-8"))


class DeploymentArtifactTests(unittest.TestCase):
    def test_task_definition_is_small_linux_x86_fargate_worker(self):
        task = _load_json("worker-task-definition.json")
        self.assertEqual(task["requiresCompatibilities"], ["FARGATE"])
        self.assertEqual(task["networkMode"], "awsvpc")
        self.assertEqual(task["cpu"], "256")
        self.assertEqual(task["memory"], "512")
        self.assertEqual(
            task["runtimePlatform"],
            {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        )

        container = task["containerDefinitions"][0]
        self.assertEqual(container["command"], ["python", "-m", "backend.worker"])
        self.assertEqual(container["logConfiguration"]["logDriver"], "awslogs")
        self.assertNotIn("portMappings", container)
        environment_names = {item["name"] for item in container["environment"]}
        self.assertEqual(
            environment_names,
            {
                "AWS_REGION",
                "FRACTAL_ROUTE_S3_BUCKET",
                "FRACTAL_ROUTE_SQS_QUEUE_URL",
            },
        )
        self.assertEqual(
            container["secrets"],
            [
                {
                    "name": "DATABASE_URL",
                    "valueFrom": (
                        "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:"
                        "parameter/fractal-route/database-url"
                    ),
                }
            ],
        )

    def test_worker_policy_is_restricted_to_consumed_apis_and_objects(self):
        policy = _load_json("worker-task-role-policy.json")
        statements = policy["Statement"]
        self.assertEqual(statements[0]["Action"], "s3:GetObject")
        self.assertEqual(
            statements[0]["Resource"],
            "arn:aws:s3:::${S3_BUCKET}/routes/*/original.gpx",
        )
        self.assertEqual(
            set(statements[1]["Action"]),
            {"sqs:ReceiveMessage", "sqs:DeleteMessage"},
        )
        self.assertEqual(
            statements[1]["Resource"],
            "arn:aws:sqs:${AWS_REGION}:${AWS_ACCOUNT_ID}:fractal-route-jobs",
        )
        self.assertNotIn("*", {statement["Resource"] for statement in statements})

    def test_execution_policy_can_only_read_database_parameter(self):
        policy = _load_json("execution-role-parameter-policy.json")
        statement = policy["Statement"][0]
        self.assertEqual(statement["Action"], "ssm:GetParameters")
        self.assertEqual(
            statement["Resource"],
            (
                "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:"
                "parameter/fractal-route/database-url"
            ),
        )

    def test_task_trust_is_only_for_ecs_tasks(self):
        policy = _load_json("ecs-tasks-trust-policy.json")
        statement = policy["Statement"][0]
        self.assertEqual(statement["Principal"], {"Service": "ecs-tasks.amazonaws.com"})
        self.assertEqual(statement["Action"], "sts:AssumeRole")


if __name__ == "__main__":
    unittest.main()
