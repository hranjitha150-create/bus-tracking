package com.campustransit.driver.activities;
import com.campustransit.driver.R;
public final class AssignedBusActivity extends BaseDriverActivity {
    @Override protected int layout() { return R.layout.activity_assigned_bus; }
    @Override protected String title() { return "My assigned bus"; }
    @Override protected boolean tripControls() { return false; }
}
