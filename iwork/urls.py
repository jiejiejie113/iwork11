"""
URL configuration for iwork project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path, include
from iwork import api_views, api_views_account, views
from iwork.alerts import api as alerts_api

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("history/", views.history_dashboard, name="history-dashboard"),

    # 实时数据API
    path("api/dashboard/realtime/", api_views.realtime_stats, name="realtime-stats"),
    path("api/dashboard/processes/", api_views.process_list, name="process-list"),
    path("api/dashboard/hourly/", api_views.hourly_stats, name="hourly-stats"),
    path("api/dashboard/flow/<str:flow_name>/", api_views.flow_stats, name="flow-stats"),
    path("api/dashboard/workorders/", api_views.workorder_list, name="workorder-list"),
    path("api/dashboard/workorders/<str:wrk_order>/", api_views.workorder_detail, name="workorder-detail"),

    # 新增API（看板改版 v2）
    path("api/dashboard/monthly-trend/", api_views.monthly_trend, name="monthly-trend"),
    path("api/dashboard/process-compare/", api_views.process_compare, name="process-compare"),
    path("api/dashboard/heatmap/", api_views.heatmap, name="heatmap"),
    path("api/dashboard/station-ranking/", api_views.station_ranking, name="station-ranking"),

    # SSE 实时推送 + 目标产量设置
    path("api/dashboard/stream/", api_views.dashboard_stream, name="dashboard-stream"),
    path("api/dashboard/set-targets/", api_views.set_targets, name="set-targets"),

    # 可信账户与目标责任管理 API
    path("api/account/me/", api_views_account.me, name="account-me"),
    path("api/account/subscriptions/", alerts_api.subscriptions, name="account-subscriptions"),
    path("api/account/notifications/", alerts_api.notifications, name="account-notifications"),
    path(
        "api/account/notifications/stream/",
        alerts_api.notification_stream,
        name="account-notifications-stream",
    ),
    path(
        "api/account/notifications/read-all/",
        alerts_api.mark_all_notifications_read,
        name="account-notifications-read-all",
    ),
    path(
        "api/account/notifications/<int:notification_id>/read/",
        alerts_api.mark_notification_read,
        name="account-notification-read",
    ),
    path(
        "api/account-admin/flow-assignments/",
        api_views_account.flow_assignments,
        name="account-admin-flow-assignments",
    ),
    path(
        "api/account-admin/flow-assignments/<int:assignment_id>/",
        api_views_account.flow_assignment_detail,
        name="account-admin-flow-assignment-detail",
    ),
    path(
        "api/account-admin/target-obligations/",
        api_views_account.target_obligations,
        name="account-admin-target-obligations",
    ),
    path(
        "api/account-admin/target-policy/",
        api_views_account.target_policy,
        name="account-admin-target-policy",
    ),

    # 历史数据API（迁移到独立路由）
    path("api/history/", include('iwork.history_urls')),

    # 生产详情 API
    path("api/dashboard/detail/stepno-overview/", api_views.stepno_overview, name="detail-stepno-overview"),
    path("api/dashboard/detail/initial-style-overview/", api_views.initial_style_overview, name="detail-initial-style-overview"),
    path("api/dashboard/detail/initial-style/", api_views.initial_style_detail, name="detail-initial-style-detail"),
    path("api/dashboard/detail/flows/", api_views.flow_overview, name="detail-flow-overview"),
    path("api/dashboard/detail/flow/<str:flow_name>/", api_views.flow_detail, name="detail-flow-detail"),
    path("api/dashboard/detail/stepno/<int:stepno>/", api_views.stepno_detail, name="detail-stepno-detail"),
    path("api/dashboard/detail/product-overview/", api_views.product_overview, name="detail-product-overview"),

    # 生产详情页面
    path("production/detail-data/", views.production_detail, name="production-detail"),
    path("production/detail-data/flow/<str:flow_name>/", views.production_detail_flow, name="production-detail-flow"),
    path("production/detail-data/stepno/<int:stepno>/", views.production_detail_stepno, name="production-detail-stepno"),
    path("production/detail-data/initial-style/", views.production_detail_initial_style, name="production-detail-initial-style"),

    # 产量看板
    path("kanban/", views.kanban_page, name="kanban-page"),
    path("api/kanban/stats/", api_views.kanban_stats, name="kanban-stats"),
    path("api/kanban/ranking/", api_views.kanban_ranking, name="kanban-ranking"),
    path("api/kanban/filter-options/", api_views.kanban_filter_options, name="kanban-filter-options"),
]
