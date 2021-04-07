from troposphere import Template, Ref, Join, Parameter, Tags, Select, GetAZs, GetAtt, Sub, If, Equals
from troposphere.ecs import Cluster as ECSCluster
from troposphere.ecs import Service as ECSService
from troposphere.ecs import TaskDefinition, ContainerDefinition, NetworkConfiguration, AwsvpcConfiguration, \
    LogConfiguration
from troposphere.ecs import Environment as ECSEnvironment
from troposphere.iam import Role, Policy
from troposphere.ec2 import InternetGateway
from troposphere.ec2 import VPCGatewayAttachment
from troposphere.ec2 import SubnetRouteTableAssociation, Subnet
from troposphere.ec2 import RouteTable, Route
from troposphere.ec2 import VPC
from troposphere.ec2 import EIP
from troposphere.ec2 import NatGateway
from troposphere.logs import LogGroup
from troposphere.codebuild import Artifacts, Source, Project
from troposphere.codebuild import Environment as CodeBuildEnvironment
from troposphere.ecr import Repository
from troposphere.iot import Policy as IoTPolicy


ref_region = Ref('AWS::Region')
ref_stack_id = Ref('AWS::StackId')
ref_stack_name = Ref('AWS::StackName')
no_value = Ref("AWS::NoValue")
ref_account = Ref("AWS::AccountId")


t = Template()

# Parameters
device_simulator_ecr_repo_param = t.add_parameter(Parameter(
    "ECRRepoName",
    Type="String",
    Description="Device Simulator ECR Repo. Modify if not using CloudFormation generated repo",
    Default="Use Built-In"
))

project_source_param = t.add_parameter(Parameter(
    "ProjectSource",
    Type="String",
    Description="Demo Project Source. Don't change unless you're using a clone/fork of the original project repo",
    Default="https://github.com/cb17/aws-iot-device-management-demo"
))

number_of_tasks = t.add_parameter(Parameter(
    "NumberOfVirtualDevices",
    Type="Number",
    Description="Number of ECS Tasks to create. Each task simulates one device",
    Default=0
))

iot_endpoint = t.add_parameter(Parameter(
    "IoTEndpoint",
    Type="String",
    Description="AWS IoT MQTT Endpoint PREFIX. ONLY INCLUDE THE CHARACTERS BEFORE THE FIRST DASH -",
    AllowedPattern="[a-zA-Z0-9]*",
    MaxLength="14"
))

vpc_cidr_prefix = t.add_parameter(Parameter(
    "VPCCIDRPrefix",
    Description="IP Address range for the VPN connected VPC",
    Default="172.31",
    Type="String",
))

account_id = t.add_parameter(Parameter(
    "ECRAccountID",
    Description="AccountID",
    Default="Optional",
    Type="String",
))
# Conditions
t.add_condition(
    "AccountIDDefault",
    Equals(
        Ref(account_id),
        "Optional"
    )
)

t.add_condition(
    "ECRRepoDefault",
    Equals(
        Ref(device_simulator_ecr_repo_param),
        "Use Built-In"
    )
)

# Resources
vpc = t.add_resource(VPC(
    "VPC",
    EnableDnsSupport="true",
    CidrBlock=Join('', [Ref(vpc_cidr_prefix), '.0.0/16']),
    EnableDnsHostnames="true",
    Tags=Tags(
            Application=Ref("AWS::StackName"),
            Network="VPC",
    )
))

igw = t.add_resource(InternetGateway(
    "InternetGateway",
    Tags=[{"Key": "Network", "Value": "igw"}],
))
igw_attachment = t.add_resource(VPCGatewayAttachment(
    "AttachGateway",
    VpcId=Ref(vpc),
    InternetGatewayId=Ref("InternetGateway"),
))
public_route_table = t.add_resource(RouteTable(
    "PublicRouteTable",
    VpcId=Ref(vpc),
    Tags=[{"Key": "Network", "Value": "public"}]
))
route_to_internet_for_public_subnets = t.add_resource(Route(
    "RouteToInternetForPublicSubnets",
    RouteTableId=Ref(public_route_table),
    DestinationCidrBlock="0.0.0.0/0",
    GatewayId=Ref(igw)
))
public_subnet_a = t.add_resource(
    Subnet(
            'PublicSubnetA',
            CidrBlock=Join('', [Ref(vpc_cidr_prefix), '.0.0/26']),
            VpcId=Ref(vpc),
            AvailabilityZone=Select("0", GetAZs(ref_region)))
)
subnet_a_route_table_association = t.add_resource(
    SubnetRouteTableAssociation(
            'PublicSubnetRouteTableAssociationA',
            SubnetId=Ref(public_subnet_a),
            RouteTableId=Ref(public_route_table),
    ))
public_subnet_b = t.add_resource(
    Subnet(
            'PublicSubnetB',
            CidrBlock=Join('', [Ref(vpc_cidr_prefix), '.0.64/26']),
            VpcId=Ref(vpc),
            AvailabilityZone=Select("1", GetAZs(ref_region)))
)
subnet_b_route_table_association = t.add_resource(
    SubnetRouteTableAssociation(
            'PublicSubnetRouteTableAssociationB',
            SubnetId=Ref(public_subnet_b),
            RouteTableId=Ref(public_route_table),
    ))
public_subnet_c = t.add_resource(
    Subnet(
            'PublicSubnetC',
            CidrBlock=Join('', [Ref(vpc_cidr_prefix), '.0.128/26']),
            VpcId=Ref(vpc),
            AvailabilityZone=Select("2", GetAZs(ref_region)))
)
subnet_c_route_table_association = t.add_resource(
    SubnetRouteTableAssociation(
            'PublicSubnetRouteTableAssociationC',
            SubnetId=Ref(public_subnet_c),
            RouteTableId=Ref(public_route_table),
    ))

nat_eip = t.add_resource(EIP(
    'NatEip',
    Domain="vpc",
))

nat = t.add_resource(NatGateway(
    'NAT',
    AllocationId=GetAtt(nat_eip, 'AllocationId'),
    SubnetId=Ref(public_subnet_a),
))

# Set up base IAM roles

device_simulator_task_role = t.add_resource(Role(
    "DeviceSimulatorTaskRole",
    Path="/",
    ManagedPolicyArns=[
        'arn:aws:iam::aws:policy/CloudWatchFullAccess',
        'arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy',
        'arn:aws:iam::aws:policy/service-role/AWSIoTThingsRegistration'
    ],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["ecs-tasks.amazonaws.com"]
            }
        }]
    },
))

iot_policy = t.add_resource(IoTPolicy(
    "DMDemoPolicy",
    PolicyDocument={
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iot:Connect",
                "Resource": Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:client/${!iot:Connection.Thing.ThingName}"),
                "Condition": {
                    "ForAllValues:StringEquals": {
                        "iot:Certificate.Subject.CommonName": "${iot:Connection.Thing.ThingName}"
                    }
                }
            },
            {
                "Effect": "Allow",
                "Action": "iot:Publish",
                "Resource": [
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topic/demofleet/${!iot:Connection.Thing.ThingName}*"),
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topic/$aws/things/${!iot:Connection.Thing.ThingName}*")
                ]
            },
            {
                "Effect": "Allow",
                "Action": "iot:Subscribe",
                "Resource": [
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topicfilter/demofleet/${!iot:Connection.Thing.ThingName}*"),
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topicfilter/$aws/things/${!iot:Connection.Thing.ThingName}*")
                ]
            },
            {
                "Effect": "Allow",
                "Action": "iot:Receive",
                "Resource": [
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topic/demofleet/${!iot:Connection.Thing.ThingName}*"),
                    Sub("arn:aws:iot:${AWS::Region}:${AWS::AccountId}:topic/$aws/things/${!iot:Connection.Thing.ThingName}*")
                ]
            }
        ]
    }
))

# Set up Fargate ECS cluster

task_log_group = t.add_resource(LogGroup(
    "TaskLogGroup",
    LogGroupName=Sub("${AWS::StackName}-IoTClientLogs"),
    RetentionInDays=30
))

ecs_cluster = t.add_resource(ECSCluster(
    "ECSServiceCluster",
))

# Set up CodeBuild environment to build Docker container
codebuild_project_name = 'AWS-IoT-DM-Demo'

device_simulator_ecr_repo = t.add_resource(Repository(
    "AWSIoTDMDemoDeviceSimulatorRepo",
    Condition="ECRRepoDefault"
))

codebuild_service_role = t.add_resource(Role(
    "CodebuildServiceRole",
    Path="/",
    Policies=[
      Policy(
          PolicyDocument={
              "Statement": [
                  {
                      "Action": [
                          "ecr:BatchCheckLayerAvailability",
                          "ecr:CompleteLayerUpload",
                          "ecr:GetAuthorizationToken",
                          "ecr:InitiateLayerUpload",
                          "ecr:PutImage",
                          "ecr:UploadLayerPart"
                      ],
                      "Resource": GetAtt(device_simulator_ecr_repo, "Arn"),
                      "Effect": "Allow"
                  },
                  {
                      "Action": [
                          "ecr:GetAuthorizationToken",
                      ],
                      "Resource": "*",
                      "Effect": "Allow"
                  }
              ],
              "Version": "2012-10-17"
          },
          PolicyName="ECRPermissions"
      ),
        Policy(
          PolicyDocument={
              "Statement": [
                  {
                      "Action": [
                          "logs:CreateLogGroup",
                          "logs:CreateLogStream",
                          "logs:PutLogEvents"
                      ],
                      "Resource": Sub(
                          "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/codebuild/" +
                          codebuild_project_name +
                          "*"
                      ),
                      "Effect": "Allow"
                  },
              ],
              "Version": "2012-10-17"
          },
          PolicyName="StandardCodeBuildPermissions"
      )
    ],
    AssumeRolePolicyDocument={
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {
                "Service": ["codebuild.amazonaws.com"]
            }
        }]
    },
    Condition="ECRRepoDefault"
))

codebuild_environment = CodeBuildEnvironment(
    "CodeBuildEnvironment",
    ComputeType='BUILD_GENERAL1_LARGE',
    Image='aws/codebuild/standard:5.0',
    Type='LINUX_CONTAINER',
    EnvironmentVariables=[
        {'Name': 'APP_NAME', 'Value': 'awsiotdmdemo'},
        {'Name': 'IMAGE_REPO', 'Value': Ref(device_simulator_ecr_repo)},
        {"Name": "IMAGE_TAG", "Value": "latest"},
        {"Name": "AWS_DEFAULT_REGION","Value": ref_region},
        {"Name": "AWS_ACCOUNT_ID","Value": ref_account}
    ],
    PrivilegedMode=True
 )

codebuild_project_source_resource = Source(
    "CodeBuildProjectSource",
    Location=Ref(project_source_param),
    Type='GITHUB'
)

build_project = t.add_resource(Project(
    "AWSIoTDMDemoProject",
    Artifacts=Artifacts(Type='NO_ARTIFACTS'),
    Environment=codebuild_environment,
    Name=codebuild_project_name,
    ServiceRole=GetAtt(codebuild_service_role, "Arn"),
    Source=codebuild_project_source_resource,
    Condition="ECRRepoDefault"
))

# Complete Docker build

# Create ECS Service and task
docker_containers = [ContainerDefinition(
    Essential=True,
    Image=If(
            "ECRRepoDefault",
            Join("", [
                If("AccountIDDefault",ref_account, Ref(account_id)),
                ".dkr.ecr.",
                ref_region,
                ".amazonaws.com/",
                Ref(device_simulator_ecr_repo)
            ]),
            Ref(device_simulator_ecr_repo_param))
        ,
    Name="IoTClient",
    LogConfiguration=LogConfiguration(
        LogDriver="awslogs",
        Options={
            "awslogs-region": ref_region,
            "awslogs-group": Ref(task_log_group),
            "awslogs-stream-prefix": "simulated-device"
        }
    ),
    Environment=[
        ECSEnvironment(
            Name="IOT_ENDPOINT",
            Value=Ref(iot_endpoint)
        ),
        ECSEnvironment(
            Name="IOT_REGION",
            Value=ref_region
        ),
        ECSEnvironment(
            Name="IOT_POLICY_NAME",
            Value=Ref(iot_policy)
        )
    ]
)]

device_simulator_task = t.add_resource(TaskDefinition(
    "DeviceSimulatorTask",
    Cpu='256',
    Memory='512',
    RequiresCompatibilities=['FARGATE'],
    NetworkMode='awsvpc',
    ContainerDefinitions=docker_containers,
    TaskRoleArn=GetAtt(device_simulator_task_role, "Arn"),
    ExecutionRoleArn=GetAtt(device_simulator_task_role, "Arn")

))

ecs_service = t.add_resource(ECSService(
    "ECSService",
    LaunchType='FARGATE',
    Cluster=Ref(ecs_cluster),
    DesiredCount=Ref(number_of_tasks),
    TaskDefinition=Ref(device_simulator_task),
    NetworkConfiguration=NetworkConfiguration(
        AwsvpcConfiguration=AwsvpcConfiguration(
            Subnets=[Ref(public_subnet_a), Ref(public_subnet_b), Ref(public_subnet_c)],
            AssignPublicIp="ENABLED"
        )
    )
))

print(t.to_json())
