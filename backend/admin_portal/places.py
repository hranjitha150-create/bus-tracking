"""Bounded, administrator-only place search for route endpoint names."""
import json
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin


def locality_query(query):
    """Try locality/city/region when a comma-separated street address has no match."""
    parts = [re.sub(r'\b\d{5,6}(?:-\d{4})?\b', '', part).strip()
             for part in query.split(',')]
    parts = [part for part in parts if part]
    if len(parts) < 3:
        return ''
    return ', '.join(parts[-3:] if len(parts) > 3 else parts[-2:])


def search_places(query):
    parameters = urlencode({'q': query, 'limit': 6, 'lang': 'en'})
    upstream = Request('https://photon.komoot.io/api/?' + parameters, headers={
        'Accept': 'application/json', 'User-Agent': 'CampusTransit/1.0 (route place search)',
    })
    with urlopen(upstream, timeout=3) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Place response too large')
    return place_labels(json.loads(raw))


def place_labels(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('features'), list):
        raise ValueError('Invalid place response')
    labels = []
    for feature in payload['features'][:20]:
        properties = feature.get('properties', {}) if isinstance(feature, dict) else {}
        if not isinstance(properties, dict):
            continue
        parts = []
        for key in ('name', 'street', 'city', 'district', 'state', 'country'):
            value = properties.get(key)
            if isinstance(value, str) and value.strip() and value.strip().casefold() not in [p.casefold() for p in parts]:
                parts.append(value.strip())
        label = ', '.join(parts)
        # Route names have a 200-character limit; never silently truncate a place.
        if label and len(label) <= 200 and label.casefold() not in [item.casefold() for item in labels]:
            labels.append(label)
        if len(labels) == 6:
            break
    return labels


class PlaceSearchAPI(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if len(query) < 3:
            return Response({'results': []})
        if len(query) > 200:
            return Response({'detail': 'Search with 200 characters or fewer.', 'results': []}, status=400)
        broadened = False
        try:
            labels = search_places(query)
            fallback = locality_query(query)
            if not labels and fallback:
                labels = search_places(fallback)
                broadened = bool(labels)
        except (URLError, OSError, ValueError):
            return Response({'detail': 'Place search is temporarily unavailable. You can enter the location manually.', 'results': []}, status=503)
        response = Response({'results': labels, 'broadened': broadened})
        response['Cache-Control'] = 'private, no-store'
        return response
