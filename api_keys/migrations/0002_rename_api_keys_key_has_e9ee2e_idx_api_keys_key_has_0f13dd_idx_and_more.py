# Generated by Django 4.2.7 on 2025-06-28 19:16

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api_keys', '0001_initial'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_key_has_0f13dd_idx',
            old_name='api_keys_key_has_e9ee2e_idx',
        ),
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_user_id_6e7352_idx',
            old_name='api_keys_user_id_22d6a5_idx',
        ),
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_expires_d03a5f_idx',
            old_name='api_keys_expires_1b5cd1_idx',
        ),
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_applica_bd4a48_idx',
            old_name='api_keys_applica_9fa18e_idx',
        ),
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_group_i_075826_idx',
            old_name='api_keys_group_i_9c1d8c_idx',
        ),
        migrations.RenameIndex(
            model_name='apikey',
            new_name='api_keys_last_us_fbf652_idx',
            old_name='api_keys_last_us_dff0f1_idx',
        ),
        migrations.RenameIndex(
            model_name='apikeyusage',
            new_name='api_key_usa_api_key_6a36ba_idx',
            old_name='api_key_usa_api_key_68a2e4_idx',
        ),
        migrations.RenameIndex(
            model_name='apikeyusage',
            new_name='api_key_usa_timesta_fd8992_idx',
            old_name='api_key_usa_timesta_00d75c_idx',
        ),
        migrations.RenameIndex(
            model_name='apikeyusage',
            new_name='api_key_usa_endpoin_a72b38_idx',
            old_name='api_key_usa_endpoin_a58866_idx',
        ),
    ]
