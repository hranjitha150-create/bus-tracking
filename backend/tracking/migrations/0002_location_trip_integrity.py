from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('tracking', '0001_initial')]
    # A Django ForeignKey validates trip_id alone. These composite foreign keys
    # also enforce the matching bus for raw SQL / bulk ORM writes.
    operations = [migrations.RunSQL(
        sql='''
            ALTER TABLE tracking_trip ADD CONSTRAINT trip_id_bus_unique UNIQUE (id, bus_id);
            ALTER TABLE tracking_buslocation ADD CONSTRAINT latest_location_trip_bus_fk
                FOREIGN KEY (trip_id, bus_id) REFERENCES tracking_trip (id, bus_id)
                DEFERRABLE INITIALLY IMMEDIATE;
            ALTER TABLE tracking_locationhistory ADD CONSTRAINT history_trip_bus_fk
                FOREIGN KEY (trip_id, bus_id) REFERENCES tracking_trip (id, bus_id)
                DEFERRABLE INITIALLY IMMEDIATE;
        ''',
        reverse_sql='''
            ALTER TABLE tracking_locationhistory DROP CONSTRAINT history_trip_bus_fk;
            ALTER TABLE tracking_buslocation DROP CONSTRAINT latest_location_trip_bus_fk;
            ALTER TABLE tracking_trip DROP CONSTRAINT trip_id_bus_unique;
        ''',
    )]
