import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from .forms import RouteForm
from .places import PlaceSearchAPI


class PlaceSearchTests(SimpleTestCase):
    def call(self, query, role='ADMIN'):
        request = APIRequestFactory().get('/api/admin/places/', {'q': query})
        if role:
            force_authenticate(request, user=SimpleNamespace(
                pk=1, is_authenticated=True, is_active=True, role=role,
            ))
        return PlaceSearchAPI.as_view()(request)

    @patch('admin_portal.places.urlopen')
    def test_results_include_context_and_deduplicate(self, upstream):
        feature = {'properties': {'name': 'Bengaluru', 'city': 'Bengaluru', 'state': 'Karnataka', 'country': 'India'}}
        upstream.return_value.__enter__.return_value.read.return_value = json.dumps({'features': [feature, feature]}).encode()
        response = self.call('Bengaluru & city')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], ['Bengaluru, Karnataka, India'])
        request = upstream.call_args.args[0]
        self.assertIn('q=Bengaluru+%26+city', request.full_url)
        self.assertEqual(upstream.call_args.kwargs['timeout'], 3)

    @patch('admin_portal.places.urlopen')
    def test_short_and_oversized_queries_do_not_call_provider(self, upstream):
        self.assertEqual(self.call('ab').data['results'], [])
        self.assertEqual(self.call('x' * 201).status_code, 400)
        upstream.assert_not_called()

    @patch('admin_portal.places.urlopen')
    def test_other_roles_and_anonymous_users_cannot_search(self, upstream):
        for role in ('STUDENT', 'DRIVER', None):
            self.assertIn(self.call('Bengaluru', role).status_code, (401, 403))
        upstream.assert_not_called()

    @patch('admin_portal.places.urlopen', side_effect=TimeoutError)
    def test_provider_failure_allows_manual_entry(self, upstream):
        response = self.call('Bengaluru')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['results'], [])
        self.assertIn('manually', response.data['detail'])

    @patch('admin_portal.places.urlopen')
    def test_invalid_and_oversized_responses_are_handled(self, upstream):
        for raw in (b'not json', b'[]', b'{}', b'x' * 65537):
            upstream.return_value.__enter__.return_value.read.return_value = raw
            self.assertEqual(self.call('Bengaluru').status_code, 503)

    @patch('admin_portal.places.urlopen')
    def test_results_fit_route_fields_and_have_a_bounded_count(self, upstream):
        features = [{'properties': {'name': 'x' * 201}}, {'properties': None}]
        features += [{'properties': {'name': f'Place {index}'}} for index in range(10)]
        upstream.return_value.__enter__.return_value.read.return_value = json.dumps({'features': features}).encode()
        self.assertEqual(self.call('Place').data['results'], [f'Place {index}' for index in range(6)])

    def test_both_route_endpoint_fields_enable_search_and_allow_free_text(self):
        form = RouteForm()
        for name in ('start_location', 'destination'):
            self.assertEqual(form.fields[name].widget.attrs['data-place-url'], '/api/admin/places/')
            self.assertEqual(form.fields[name].clean('Manually entered campus'), 'Manually entered campus')

    @patch('admin_portal.places.search_places')
    def test_full_address_over_100_characters_is_searched_then_broadened(self, search):
        search.side_effect = [[], ['Gokulam, Mysuru, Karnataka, India']]
        address = '2nd Floor, KVN Complex, Mahadeswara Badavane, Vijay Nagar 2nd Stage, Gokulam, Mysuru, Karnataka 570016'
        self.assertGreater(len(address), 100)
        response = self.call(address)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['broadened'])
        self.assertEqual(search.call_args_list[0].args[0], address)
        self.assertEqual(search.call_args_list[1].args[0], 'Gokulam, Mysuru, Karnataka')

    @patch('admin_portal.places.search_places')
    def test_destination_fallback_removes_street_and_postcode(self, search):
        search.side_effect = [[], ['Sriramapura, Karnataka, India']]
        response = self.call('Ring Rd, Sriramapura, BEML Nagar, Sriramapura, Karnataka 570033')
        self.assertTrue(response.data['broadened'])
        self.assertEqual(search.call_args.args[0], 'BEML Nagar, Sriramapura, Karnataka')

    @patch('admin_portal.places.search_places')
    def test_no_fallback_when_exact_address_matches(self, search):
        search.return_value = ['Gokulam, Mysuru, Karnataka']
        response = self.call('Gokulam, Mysuru, Karnataka')
        self.assertFalse(response.data['broadened'])
        search.assert_called_once()

    @patch('admin_portal.places.search_places', return_value=[])
    def test_fallback_is_bounded_and_can_still_return_no_match(self, search):
        response = self.call('Building, Area, City, State 570016')
        self.assertEqual(search.call_count, 2)
        self.assertEqual(response.data['results'], [])
        self.assertFalse(response.data['broadened'])
