import datetime
import json

from time import sleep
from urllib import parse
from uuid import uuid4

import jmespath
import jwt
import requests


COMMAND = '/$export'
HEADERS = {
    'Accept': 'application/fhir+json',
    'Prefer': 'respond-async',
}
VALID_QUERY_PARAMS = [
    '_outputFormat',
    '_since',
    '_type',
]
MANIFEST_URLS = jmespath.compile('output[*].url')


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
                'grant_type': 'client_credentials',
                'scope': 'system/*.*',
                'client_assertion_type':
                    'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
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
            auth_location=None,
            client_id=None,
            client_url=None,
            private_key=None,
            username=None,
            password=None):
        self.server = server
        self.session = requests.Session()
        # TODO - what kind of auth interface does the server want us to use?
#        self.session.auth = BulkDataAuth(
#            auth_location,
#            client_id,
#            client_url,
#            private_key
#        )
        self.session.auth = (username, password)
        self.session.headers = HEADERS

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.close()

    def issue(self, url, **params):
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        # TODO this all assumes OAuth
        #        except requests.HTTPError as exc:
        #            if response.status_code == 401:
        #                self.session.auth.token = None
        #                response = self.issue(url, **params)
        #            else:
        #                raise exc
        return response

    def provision(self, compartment=None, **query_params):
        # TODO 3 options: /$export, /Group/[id]/$export, /Patient/$export
        params = {
            k:v for (k, v) in query_params.items()
            if k in VALID_QUERY_PARAMS
        }
        response = self.issue(self.server+COMMAND, **params)
        content = response.headers.get('Content-Location')
        # NOTE `content` should be an absolute URL but we're being kind :)
        try:
            assert parse.urlparse(content).scheme
        except AssertionError:
            content = urljoin(self.server, content)
        while True:
            # TODO backoff
            # TODO would be a good place for asyncio
            sleep(0.5)
            response = self.issue(content)
            if response.status_code == 200:
                self.manifest = MANIFEST_URLS.search(response.json())
                return

    def iter_json(self):
        if not self.provisioned:
            return
        for url in self.manifest:
            data = self.issue(url)
            for item in data.iter_lines():
                yield json.loads(item)
