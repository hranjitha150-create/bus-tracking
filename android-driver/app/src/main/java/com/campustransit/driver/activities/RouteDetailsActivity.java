package com.campustransit.driver.activities;
import com.campustransit.driver.R;
public final class RouteDetailsActivity extends BaseDriverActivity {
    @Override protected int layout() { return R.layout.activity_route_details; }
    @Override protected String title() { return "Route and stops"; }
    @Override protected boolean routeScreen() { return true; }
    @Override protected boolean tripControls() { return false; }
}
