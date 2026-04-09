import csv
import io
import os
from datetime import datetime, timedelta

from google.cloud import monitoring_v3
from google.cloud import compute_v1
from google.cloud import resourcemanager_v3

import smtplib
from email.message import EmailMessage


EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")


# ---------------------------------------------------
# LIST ALL PROJECTS
# ---------------------------------------------------

def list_projects():

    client = resourcemanager_v3.ProjectsClient()

    return [
        project.project_id
        for project in client.search_projects()
        if project.state.name == "ACTIVE"
    ]


# ---------------------------------------------------
# LIST INSTANCES PER PROJECT
# ---------------------------------------------------

def list_instances(project_id):

    instance_client = compute_v1.InstancesClient()

    request = compute_v1.AggregatedListInstancesRequest(
        project=project_id
    )

    instances = []

    for zone, response in instance_client.aggregated_list(
        request=request
    ):

        if response.instances:

            for instance in response.instances:

                zone_name = zone.split("/")[-1]

                instances.append(
                    (
                        instance.name,
                        instance.id,
                        zone_name
                    )
                )

    return instances


# ---------------------------------------------------
# FETCH AVG + MAX CPU UTILIZATION
# ---------------------------------------------------

def fetch_cpu_metrics(project_id, instance_id):

    client = monitoring_v3.MetricServiceClient()

    interval = monitoring_v3.TimeInterval(
        {
            "end_time": datetime.utcnow(),
            "start_time": datetime.utcnow() - timedelta(days=7),
        }
    )

    metric_filter = f'''
metric.type="compute.googleapis.com/instance/cpu/utilization"
AND resource.labels.instance_id="{instance_id}"
'''

    avg_aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": 604800},
            "per_series_aligner":
            monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
        }
    )

    max_aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": 604800},
            "per_series_aligner":
            monitoring_v3.Aggregation.Aligner.ALIGN_MAX,
        }
    )

    avg_cpu = 0
    max_cpu = 0

    avg_series = client.list_time_series(
        request={
            "name": f"projects/{project_id}",
            "filter": metric_filter,
            "interval": interval,
            "aggregation": avg_aggregation,
        }
    )

    for series in avg_series:

        for point in series.points:

            avg_cpu = round(point.value.double_value * 100, 2)

    max_series = client.list_time_series(
        request={
            "name": f"projects/{project_id}",
            "filter": metric_filter,
            "interval": interval,
            "aggregation": max_aggregation,
        }
    )

    for series in max_series:

        for point in series.points:

            max_cpu = round(point.value.double_value * 100, 2)

    return avg_cpu, max_cpu


# ---------------------------------------------------
# SEND EMAIL WITH CSV ATTACHMENT
# ---------------------------------------------------

def send_email(csv_bytes):

    msg = EmailMessage()

    msg["Subject"] = "Weekly GCP VM CPU Utilization Report"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    msg.set_content(
        "Attached is the weekly CPU utilization report."
    )

    msg.add_attachment(
        csv_bytes,
        maintype="text",
        subtype="csv",
        filename="cpu_report.csv",
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:

        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)

        smtp.send_message(msg)


# ---------------------------------------------------
# MAIN ENTRY FUNCTION
# ---------------------------------------------------

def generate_report(request):

    csv_buffer = io.StringIO()

    writer = csv.writer(csv_buffer)

    writer.writerow(
        [
            "Project",
            "Instance",
            "Zone",
            "CPU Avg (7d) %",
            "CPU Max (7d) %",
        ]
    )

    projects = list_projects()

    for project in projects:

        try:

            instances = list_instances(project)

            for instance_name, instance_id, zone in instances:

                avg_cpu, max_cpu = fetch_cpu_metrics(
                    project,
                    instance_id
                )

                writer.writerow(
                    [
                        project,
                        instance_name,
                        zone,
                        avg_cpu,
                        max_cpu,
                    ]
                )

        except Exception as e:

            print(f"Skipping project {project}: {e}")

    send_email(csv_buffer.getvalue().encode())

    return "Report sent successfully"
