from django.urls import path

from workflow import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("leave/", views.leave_list, name="leave_list"),
    path("leave/<str:pk>/", views.leave_detail, name="leave_detail"),
    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/<str:pk>/", views.expense_detail, name="expense_detail"),
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/<str:pk>/", views.employee_detail, name="employee_detail"),
    path("inbox/", views.inbox, name="inbox"),
    path("new/", views.new_request, name="new_request"),
    path("api/preview/<str:kind>/", views.api_preview, name="api_preview"),
    path("api/submit/<str:kind>/", views.api_submit, name="api_submit"),
    path("analyst/", views.analyst, name="analyst"),
    path("policies/", views.policies, name="policies"),
]
