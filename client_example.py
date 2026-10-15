"""内网轮询示例：python client_example.py --url https://sms.example.com --token xxx --platform 拼多多"""
import argparse, json, time, urllib.error, urllib.parse, urllib.request


def wait_code(url, token, keyword="", timeout=120, interval=3, since=None, platform=None):
    since = since if since is not None else time.time() - 5
    params = {"keyword": keyword, "since": since}
    if platform:
        params["platform"] = platform
    q = urllib.parse.urlencode(params)
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(f"{url.rstrip('/')}/code?{q}", headers={"X-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)["sms_code"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        except urllib.error.URLError:
            pass
        time.sleep(interval)
    raise TimeoutError("等待验证码超时")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--keyword", default="")
    p.add_argument("--platform", default=None, help="短信签名，如 拼多多（精确匹配）")
    p.add_argument("--timeout", type=int, default=120)
    a = p.parse_args()
    print(wait_code(a.url, a.token, a.keyword, a.timeout, platform=a.platform))
