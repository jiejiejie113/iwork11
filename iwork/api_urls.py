from django.urls import path
from iwork import api_views

app_name = 'api'

urlpatterns = [
    path('stats/realtime/', api_views.realtime_stats, name='realtime_stats'),
    path('stats/hourly/', api_views.hourly_stats, name='hourly_stats'),
    path('stats/flow/<str:flow_name>/', api_views.flow_stats, name='flow_stats'),
    path('workorders/', api_views.workorder_list, name='workorder_list'),
    path('workorders/<str:wrk_order>/', api_views.workorder_detail, name='workorder_detail'),
]