#!/usr/bin/env python3
import csv
import requests
import io
import sys
import time
import argparse
import math
import xml.etree.ElementTree as ET
import subprocess
import shutil
from urllib.parse import urlparse


class Speedtest:
    def __init__(self):
        self.server_list_url = "https://gist.githubusercontent.com/stas-sl/eecfbf3ba2497d1171dcb28cc0fb73ee/raw/"
        self.config_url = "https://www.speedtest.net/speedtest-config.php"
        self.servers = []
        self.client_info = {}
        self.session = requests.Session()

    def get_config(self):
        try:
            response = self.session.get(self.config_url, timeout=10)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            client = root.find('client').attrib
            self.client_info = {
                'ip': client.get('ip'),
                'lat': float(client.get('lat')),
                'lon': float(client.get('lon')),
                'isp': client.get('isp'),
                'city': client.get('city', 'Unknown')
            }
        except Exception:
            self.client_info = {'ip': 'Unknown', 'lat': 0.0, 'lon': 0.0, 'isp': 'Unknown', 'city': 'Unknown'}

    def calculate_distance(self, origin, destination):
        lat1, lon1 = origin
        lat2, lon2 = destination
        radius = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(
            dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c

    def fetch_servers(self):
        try:
            response = self.session.get(self.server_list_url, timeout=10)
            response.raise_for_status()
            f = io.StringIO(response.text)
            reader = csv.DictReader(f)
            self.servers = list(reader)
        except Exception as e:
            print(f"ERROR: Could not retrieve server list: {e}")
            sys.exit(1)

    def list_servers(self, country_arg):
        if not self.servers:
            self.fetch_servers()
        if country_arg == "ALL":
            target_country = input("Enter country to filter by (or press Enter for ALL): ").strip().lower()
        else:
            target_country = country_arg.strip().lower()

        header = f"{'ID':<8} | {'Country':<15} | {'City':<20} | {'Sponsor':<25} | {'ISP ID':<10}"
        divider = "-" * len(header)
        print(f"\n{header}\n{divider}")
        for s in self.servers:
            if not target_country or target_country in s.get('country', '').lower():
                print(f"{s.get('id', 'N/A'):<8} | {s.get('country', 'N/A')[:15]:<15} | "
                      f"{s.get('name', 'N/A')[:20]:<20} | {s.get('sponsor', 'N/A')[:25]:<25} | "
                      f"{s.get('isp_id', 'N/A'):<10}")
        print(divider + "\n")

    def get_latency(self, url):
        """Measures latency to the host using a small request."""
        try:
            start = time.time()
            self.session.head(url, timeout=5)
            return (time.time() - start) * 1000
        except Exception:
            return 0

    def run_mtr(self, host):
        """Executes MTR in report format if the command is available."""
        if not shutil.which("mtr"):
            return None
        try:
            # -r: report, -c 5: 5 cycles, -z: aslookup
            result = subprocess.run(["mtr", "-r", "-c", "5", "-z", host],
                                    capture_output=True, text=True, timeout=30)
            return result.stdout
        except Exception:
            return None

    def perform_download(self, server_url):
        base_url = server_url.split('/upload.php')[0]
        download_url = f"{base_url}/random4000x4000.jpg"
        total_bytes, duration = 0, 10
        start_time = time.time()
        end_time = start_time + duration
        try:
            while time.time() < end_time:
                with self.session.get(download_url, stream=True, timeout=10) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if time.time() >= end_time: break
                        if chunk: total_bytes += len(chunk)
            actual_duration = time.time() - start_time
            return (total_bytes * 8) / (actual_duration * 1000000)
        except Exception:
            return 0

    def perform_upload(self, server_url):
        duration = 10
        start_time = time.time()
        end_time = start_time + duration
        total_sent = [0]

        def data_generator():
            chunk = b'0' * (1024 * 1024)
            while time.time() < end_time:
                total_sent[0] += len(chunk)
                yield chunk

        try:
            self.session.post(server_url, data=data_generator(), timeout=15)
            actual_duration = time.time() - start_time
            return (total_sent[0] * 8) / (actual_duration * 1000000)
        except Exception:
            actual_duration = time.time() - start_time
            return (total_sent[0] * 8) / (actual_duration * 1000000) if total_sent[0] > 0 else 0

    def run(self, args):
        if args.listservers:
            self.list_servers(args.listservers)
            return

        if args.server:
            if not self.servers:
                self.fetch_servers()
            self.get_config()

            target_server = next((s for s in self.servers if s['id'] == str(args.server)), None)
            if not target_server:
                print(f"ERROR: Server ID {args.server} not found.")
                return

            # Parse destination host for latency and MTR
            parsed_url = urlparse(target_server['url'])
            dest_host = parsed_url.hostname

            dist = self.calculate_distance(
                (self.client_info['lat'], self.client_info['lon']),
                (float(target_server['lat']), float(target_server['lon']))
            )

            latency = self.get_latency(target_server['url'])

            print(
                f"Testing from: {self.client_info['ip']} ({self.client_info['isp']}) | City: {self.client_info['city']}")
            print(f"Hosted by: {target_server['sponsor']}")
            print(f"City: {target_server['name']}")
            print(f"Distance: {dist:.2f} km")
            print(f"Latency: {latency:.2f} ms")
            print(f"Host: {dest_host}")

            mtr_res = self.run_mtr(dest_host)
            if mtr_res:
                print("\nMTR Test Result:")
                print(mtr_res)

            dl_speed = self.perform_download(target_server['url'])
            if dl_speed > 0:
                print(f"Download: {dl_speed:.2f} Mbits/s")

            ul_speed = self.perform_upload(target_server['url'])
            if ul_speed > 0:
                print(f"Upload: {ul_speed:.2f} Mbits/s")
        else:
            print("Usage: speedtest speedtest -s [ID] or -l [Country]")


