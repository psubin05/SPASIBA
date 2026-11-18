"""Local HTTP route timing; run the API first, then python -m tools.benchmark_route."""

import json
from statistics import mean, median
from time import perf_counter
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    url = 'http://127.0.0.1:8000/route?' + urlencode({'from': 'QR-B2-ENT1', 'to': 'B2-A-03'})
    timings = []
    for i in range(105):
        started = perf_counter()
        with urlopen(url, timeout=5) as response:
            result = json.load(response)
        elapsed = (perf_counter() - started) * 1000
        if result['distance_m'] != 16:
            raise ValueError('Unexpected sample route')
        if i >= 5:
            timings.append(elapsed)
    report = {'scope': 'localhost HTTP, sample QR-B2-ENT1 to B2-A-03, 5 warmups',
              'samples': len(timings), 'mean_ms': round(mean(timings), 3),
              'median_ms': round(median(timings), 3),
              'p95_ms': round(sorted(timings)[94], 3), 'max_ms': round(max(timings), 3)}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
