import requests
from requests.auth import HTTPBasicAuth
import base64

class TrendMicro():
    def __init__(self, url, username, api_key):
        self.url = f"https://{url}"
        self.username = username
        self.api_key = api_key

        auth_string = f"{username}:{api_key}"

        auth_bytes = auth_string.encode('utf-8')
        base64_bytes = base64.b64encode(auth_bytes)
        base64_string = base64_bytes.decode('utf-8')

        self.headers = {
            "Authorization": f"Basic {base64_string}"
        }

    def list_policy_event_logs(self, start, end, token):
        url = ""
        if token != "": 
            url = f"{self.url}/api/v1/log/policyeventlog?start={start}&end={end}&token={token}"      
        else: 
            url = f"{self.url}/api/v1/log/policyeventlog?start={start}&end={end}"
        response = requests.get(url=url, headers=self.headers, verify=False)
        return response
    
    def list_mail_tracking_logs(self, type, start, end, token):
        url = ""
        if token != "": 
            url = f"{self.url}/api/v1/log/mailtrackinglog?type={type}&start={start}&end={end}&token={token}"
        else: 
            url = f"{self.url}/api/v1/log/mailtrackinglog?type={type}&start={start}&end={end}"
        response = requests.get(url=url, headers=self.headers, verify=False)
        return response