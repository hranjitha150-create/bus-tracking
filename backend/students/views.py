from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from .queries import dashboard_snapshot


def student_required(view):
    @never_cache
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.role != 'STUDENT':
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@student_required
def portal(request, section='overview'):
    titles = {'overview': 'Your campus commute', 'bus': 'My bus', 'tracking': 'Live tracking',
              'route': 'Route & stops', 'pickup': 'My pickup stop', 'profile': 'My profile'}
    data = dashboard_snapshot(request.user)
    return render(request, 'students/portal.html', {'title': titles[section], 'section': section, 'snapshot': data,
                                                  'has_map': section in ('tracking', 'route', 'pickup')})
