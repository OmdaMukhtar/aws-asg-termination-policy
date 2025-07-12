import json
import boto3 # type: ignore
import logging
import urllib.parse

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# SNS Topic ARN to send emails to admins
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:381492318039:InstanceTerminationApproval"

# Replace with your API Gateway domain name
API_BASE_URL = "https://63fr6u2rbh.execute-api.us-east-1.amazonaws.com/prod"

autoscaling = boto3.client('autoscaling')
sns = boto3.client('sns')

def lambda_handler(event, context):
    
    logger.info("Event received: %s", json.dumps(event))

    # CASE 1: Triggered by Auto Scaling Lifecycle event
    if event.get("detail-type") == "EC2 Instance-terminate Lifecycle Action":
        detail = event["detail"]
        asg_name = detail["AutoScalingGroupName"]
        hook_name = detail["LifecycleHookName"]
        instance_id = detail["EC2InstanceId"]
        token = detail["LifecycleActionToken"]

        # Encode payload for approval links for safty
        approval_payload = urllib.parse.quote_plus(json.dumps({
            "asg": asg_name,
            "hook": hook_name,
            "token": token,
            "instance": instance_id
        }))

        approve_url = f"{API_BASE_URL}/lifecycle?payload={approval_payload}&action=continue"
        deny_url = f"{API_BASE_URL}/lifecycle?payload={approval_payload}&action=abandon"

        message = f"""
🚨 EC2 Instance Termination Approval Required 🚨

Instance ID: {instance_id}
Auto Scaling Group: {asg_name}

✅ Approve: {approve_url}
❌ Deny:    {deny_url}
"""

        # Send email to admin via SNS
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Approval Needed: EC2 Instance Termination",
            Message=message
        )

        logger.info("Approval email sent.")
        return {"statusCode": 200, "body": "SNS notification sent."}

    # CASE 2: Triggered by API Gateway from approval link
    elif "queryStringParameters" in event:
        params = event["queryStringParameters"]
        action = params.get("action", "").lower()
        approval_token = params.get("payload")

        if not approval_token or action not in ["continue", "abandon"]:
            return {"statusCode": 400, "body": "Missing or invalid parameters."}

        try:
            payload = json.loads(urllib.parse.unquote_plus(approval_token))
            hook_name = payload["hook"]
            asg_name = payload["asg"]
            token = payload["token"]
            instance_id = payload["instance"]
        except Exception as e:
            logger.error("Error parsing token: %s", str(e))
            return {"statusCode": 400, "body": "Invalid payload."}

        result = "CONTINUE" if action == "continue" else "ABANDON"


        try:
            autoscaling.complete_lifecycle_action(
                LifecycleHookName=hook_name,
                AutoScalingGroupName=asg_name,
                LifecycleActionToken=token,
                LifecycleActionResult=result
            )
            logger.info(f"Lifecycle {result} sent for {instance_id}")
            return {
                "statusCode": 200,
                "body": f"Instance {instance_id} termination {result.lower()}ed."
            }
        except Exception as e:
            logger.error("Failed to complete lifecycle action: %s", str(e))
            return {"statusCode": 500, "body": "Failed to complete lifecycle action."}


    return {"statusCode": 400, "body": "Invalid event source."}
