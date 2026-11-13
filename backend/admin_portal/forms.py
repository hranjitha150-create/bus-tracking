from django import forms
from django.urls import reverse
from django.db.models import F
from accounts.models import CustomUser
from buses.models import Bus
from routes.models import Route, BusStop
from students.models import Student
from drivers.models import Driver
from assignments.models import DriverAssignment


class StyledForm:
    def style(self):
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'


class BusForm(StyledForm, forms.ModelForm):
    class Meta:
        model = Bus
        fields = ['bus_number', 'registration_number', 'capacity', 'description', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class PersonForm(StyledForm, forms.Form):
    full_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(required=False, max_length=128, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), help_text='Required for a new account. Leave empty when editing to keep the current password.')
    phone = forms.CharField(max_length=20)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, kind, instance=None, **kwargs):
        self.kind, self.instance = kind, instance
        super().__init__(*args, **kwargs)
        if kind == 'student':
            self.fields.update(enrollment_number=forms.CharField(max_length=50), department=forms.CharField(max_length=100), semester=forms.IntegerField(min_value=1, max_value=12))
        else:
            self.fields['license_number'] = forms.CharField(max_length=50)
        if instance:
            for field in self.fields:
                if field != 'password':
                    self.initial[field] = getattr(instance.user, field) if field in ('full_name', 'email', 'is_active') else getattr(instance, field)
        else:
            self.fields['password'].required = True
        self.style()


class RouteForm(StyledForm, forms.ModelForm):
    class Meta:
        model = Route
        fields = ['route_code', 'route_name', 'start_location', 'destination', 'direction', 'is_active', 'geometry']
        widgets = {'geometry': forms.Textarea(attrs={'rows': 3})}
        help_texts = {'geometry': 'Authoritative road GeoJSON LineString, using [longitude, latitude]. Required for ETA and stop distances. With {}, only GPS position tracking and approximate stop connections are available.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['route_code'].disabled = True
        self.style()
        for name in ('start_location', 'destination'):
            self.fields[name].widget.attrs.update({
                'data-place-search': 'true', 'data-place-url': reverse('admin-place-search'),
                'autocomplete': 'off', 'placeholder': 'Search a town, area or landmark',
            })
            self.fields[name].help_text = 'Type at least 3 characters and choose a place, or enter a location manually.'

    def clean_geometry(self):
        return self.cleaned_data.get('geometry') or {}


class StopForm(StyledForm, forms.ModelForm):
    stop_order = forms.IntegerField(min_value=1, required=False, help_text='For a new stop: insert at this position, or leave empty to append.')
    class Meta:
        model = BusStop
        fields = ['name', 'latitude', 'longitude', 'address']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields.pop('stop_order')
        self.style()


class StudentAssignmentForm(StyledForm, forms.Form):
    student = forms.ModelChoiceField(queryset=Student.objects.none())
    bus = forms.ModelChoiceField(queryset=Bus.objects.none())
    pickup_stop = forms.ModelChoiceField(queryset=BusStop.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.filter(user__is_active=True).select_related('user').order_by('user__full_name')
        self.fields['student'].label_from_instance = lambda obj: f'{obj.user.full_name} · {obj.enrollment_number}'
        self.fields['bus'].queryset = Bus.objects.filter(is_active=True, driver_assignments__is_active=True, driver_assignments__route__is_active=True).annotate(assigned_route_code=F('driver_assignments__route__route_code')).order_by('bus_number')
        self.fields['bus'].label_from_instance = lambda obj: f'{obj.bus_number} · {obj.assigned_route_code}'
        self.fields['bus'].help_text = 'The bus determines the route. Choose a pickup stop from that route below.'
        bus_id = self.data.get('bus') if self.is_bound else self.initial.get('bus')
        if str(bus_id).isdigit():
            route_ids = DriverAssignment.objects.filter(bus_id=bus_id, is_active=True, route__is_active=True).values_list('route_id', flat=True)
            self.fields['pickup_stop'].queryset = BusStop.objects.filter(route_stops__route_id__in=route_ids).order_by('route_stops__stop_order').distinct()
        self.fields['pickup_stop'].label_from_instance = lambda obj: obj.name
        self.style()


class DriverAssignmentForm(StyledForm, forms.Form):
    driver = forms.ModelChoiceField(queryset=Driver.objects.none())
    bus = forms.ModelChoiceField(queryset=Bus.objects.none())
    route = forms.ModelChoiceField(queryset=Route.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['driver'].queryset = Driver.objects.filter(user__is_active=True).select_related('user').order_by('user__full_name')
        self.fields['driver'].label_from_instance = lambda obj: f'{obj.user.full_name} · {obj.license_number}'
        self.fields['bus'].queryset = Bus.objects.filter(is_active=True).order_by('bus_number')
        self.fields['route'].queryset = Route.objects.filter(is_active=True).order_by('route_code')
        self.fields['route'].label_from_instance = lambda obj: f'{obj.route_code} · {obj.route_name}'
        self.style()


class ImportForm(StyledForm, forms.Form):
    route_code = forms.CharField(max_length=30, required=False, help_text='Leave blank to use the CSV route ID, or enter a different code to copy its stops into that route. Existing routes with the entered code are updated.')
    route_name = forms.CharField(max_length=150, required=False, help_text='Optional display name for the route.')
    file = forms.FileField(label='Route stops CSV', widget=forms.ClearableFileInput(attrs={'accept': '.csv,text/csv'}))
    direction = forms.ChoiceField(choices=Route.Direction.choices, initial='TO_COLLEGE')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()

    def clean_file(self):
        upload = self.cleaned_data['file']
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError('CSV must be at most 2 MB.')
        return upload


class BulkStopForm(StyledForm, forms.Form):
    name = forms.CharField(max_length=200)
    latitude = forms.DecimalField(max_digits=10, decimal_places=7, min_value=-90, max_value=90)
    longitude = forms.DecimalField(max_digits=10, decimal_places=7, min_value=-180, max_value=180)
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


BulkStopFormSet = forms.formset_factory(BulkStopForm, extra=1, min_num=1,
    validate_min=True, max_num=200, validate_max=True, absolute_max=200, can_delete=True)
