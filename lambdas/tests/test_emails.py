import boto3

import create_booking
from conftest import booking_body, call, event


def test_confirmation_email_sent_when_sender_is_verified(fake_aws, monkeypatch):
    monkeypatch.setenv("SENDER_EMAIL", "cafe@example.com")
    boto3.client("sesv2").create_email_identity(EmailIdentity="cafe@example.com")
    status, body, _ = call(create_booking.handler, event(body=booking_body()))
    assert status == 201 and body["emailSent"] is True


def test_email_failure_never_breaks_the_booking(fake_aws, monkeypatch):
    monkeypatch.setenv("SENDER_EMAIL", "not-verified@example.com")  # SES refuses unverified senders
    status, body, _ = call(create_booking.handler, event(body=booking_body()))
    assert status == 201 and body["emailSent"] is False
    assert fake_aws.scan(TableName="bookings")["Count"] == 1
