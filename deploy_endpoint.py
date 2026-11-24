import os, re, sys, time
import boto3

sm = boto3.client("sagemaker")
package_arn = sys.argv[1]

region = os.environ.get("AWS_REGION", "ap-south-1")
ssm = boto3.client("ssm", region_name=region)


def setting(env_name, ssm_name):
    """Environment variable first (local runs / CI), then SSM Parameter Store."""
    return (
        os.environ.get(env_name)
        or ssm.get_parameter(Name=ssm_name)["Parameter"]["Value"]
    )


role = setting(
    "SAGEMAKER_EXECUTION_ROLE_ARN", "/fraud-mlops/sagemaker-execution-role-arn"
)
endpoint = setting("ENDPOINT_NAME", "/fraud-mlops/endpoint-name")
instance_type = setting("ENDPOINT_INSTANCE_TYPE", "/fraud-mlops/endpoint-instance-type")

package_arn = sys.argv[1]
# Only deploy packages from our own model group (the dispatch payload is external input)
if not re.fullmatch(
    r"arn:aws:sagemaker:[a-z0-9-]+:\d{12}:model-package/FraudDetectionModelGroup/\d+",
    package_arn,
):
    sys.exit(f"Refusing to deploy unexpected ARN: {package_arn}")

stamp = time.strftime("%Y%m%d-%H%M%S")

sm.create_model(
    ModelName=f"fraud-model-{stamp}",
    ExecutionRoleArn=role,
    Containers=[{"ModelPackageName": package_arn}],
)
sm.create_endpoint_config(
    EndpointConfigName=f"fraud-config-{stamp}",
    ProductionVariants=[
        {
            "VariantName": "AllTraffic",
            "ModelName": f"fraud-model-{stamp}",
            "InitialInstanceCount": 1,
            "InstanceType": "ml.m5.large",
        }
    ],
)
exists = any(
    e["EndpointName"] == endpoint
    for e in sm.list_endpoints(NameContains=endpoint)["Endpoints"]
)
if exists:
    # Blue/green: new fleet is provisioned before traffic moves over
    sm.update_endpoint(
        EndpointName=endpoint, EndpointConfigName=f"fraud-config-{stamp}"
    )
else:
    sm.create_endpoint(
        EndpointName=endpoint, EndpointConfigName=f"fraud-config-{stamp}"
    )
sm.get_waiter("endpoint_in_service").wait(EndpointName=endpoint)
print("Model deployed to real-time endpoint")
