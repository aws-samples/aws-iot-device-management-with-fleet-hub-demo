FROM public.ecr.aws/amazonlinux/amazonlinux:latest
RUN yum install -y amazon-linux-extras wget
RUN amazon-linux-extras install python3
RUN pip3 install pip --upgrade
RUN pip3 install boto3 AWSIoTPythonSDK requests cryptography
ADD . /home
WORKDIR /home
RUN wget -O /tmp/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem

CMD python3 iot_client.py
