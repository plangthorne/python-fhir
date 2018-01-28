import datetime
import json

from time import sleep
from uuid import uuid4

import jwt
import requests


ASSERTION_TYPE = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
COMMAND = '/$export'
GRANT_TYPE = 'client_credentials'
HEADERS = {
    'Accept': 'application/fhir+ndjson',
    'Prefer': 'respond-async',
}
SCOPE = 'system/*.*'

VALID_QUERY_PARAMS = [
    '_outputFormat',
    '_since',
    '_type',
]


def parse_manifest(response):
    return [_.get('url') for _ in response.json()['output']]

class BulkDataAuth(requests.auth.AuthBase):

    token = None

    def __init__(self, auth_location, client_id, client_url, private_key):
        self.auth_location = auth_location
        self.client_id = client_id
        self.client_url = client_url
        self.private_key = private_key

    def __call__(self, request):
        if not self.token:
            expiration = datetime.datetime.now() + datetime.timedelta(minutes=5)
            payload = {
                'grant_type': GRANT_TYPE,
                'scope': SCOPE,
                'client_assertion_type': ASSERTION_TYPE,
                'client_assertion': jwt.encode({
                    'iss': self.client_url,
                    'sub': self.client_id,
                    'aud': self.auth_location,
                    'exp': int(expiration.strftime('%s')),
                    'jti': uuid4().hex,
                }, self.private_key, algorithm='RS256'),
            }
            response = requests.post(
                self.auth_location,
                data=payload,
                timeout=30
            )
            response.raise_for_status()
            self.token = response.json()['access_token']
        request.headers['Authorization'] = 'Bearer %s' % self.token
        return request

class BulkDataClient(object):

    manifest = []

    @property
    def provisioned(self):
        return bool(self.manifest)

    def __init__(
            self,
            server,
            auth_location,
            client_id,
            client_url,
            private_key):
        self.server = server
        self.session = requests.Session()
        self.session.auth = BulkDataAuth(
            auth_location,
            client_id,
            client_url,
            private_key
        )
        self.session.headers = HEADERS

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.close()

    def issue(self, url, **params):
        response = self.session.get(url, params=params, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            if response.status_code == 401:
                self.session.auth.token = None
                response = self.issue(url, **params)    # if credentials are bad
                                                        # recursion will stop at
                                                        # token endpoint
            else:
                raise exc
        return response

    def provision(self, group_id=None, **query_params):
        params = {
            k:v for (k, v) in query_params.items()
            if k in VALID_QUERY_PARAMS
        }
        endpoint = '/Group/%s' % group_id if group_id else '/Patient'
        response = self.issue(self.server+endpoint+COMMAND, **params)
        content = response.headers.get('Content-Location')
        while True:
            sleep(0.5)
            response = self.issue(content)
            if response.status_code == 200:
                self.manifest = parse_manifest(response)
                return

    def iter_json(self):
        if not self.provisioned:
            return
        for url in self.manifest:
            data = self.issue(url)
            for item in data.iter_lines():
                yield json.loads(item)
