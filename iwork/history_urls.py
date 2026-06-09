from django.urls import path
from iwork import api_views_local

app_name = 'history'

urlpatterns = [
    path('date/<str:target_date>/', api_views_local.local_date_stats, name='local-date-stats'),
    path('dates/', api_views_local.available_dates, name='available-dates'),
    path('sync/<str:target_date>/', api_views_local.sync_date, name='sync-date'),
]
