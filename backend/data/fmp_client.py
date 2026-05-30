import requests

class FMPClient:
    def __init__(self, api_key:str):
        self.api_key = api_key
        self.base_url = 'https://financialmodelingprep.com/stable'

    def profile(self, ticker:str):
        url = f'{self.base_url}/profile?symbol={ticker}&apikey={self.api_key}'
        return requests.get(url, timeout=30).json()

    def quote(self, ticker:str):
        url = f'{self.base_url}/quote?symbol={ticker}&apikey={self.api_key}'
        return requests.get(url, timeout=30).json()

    def key_metrics(self, ticker:str):
        url = f'{self.base_url}/key-metrics?symbol={ticker}&apikey={self.api_key}'
        return requests.get(url, timeout=30).json()
