# Copyright 2016-2017 Nitor Creations Oy
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Main module for nitor-deploy-tools
"""

PATH_COMMANDS = [
    'bin/create-shell-archive.sh',
    'bin/ensure-letsencrypt-certs.sh',
    'bin/lastpass-fetch-notes.sh',
    'bin/lpssh',
    'bin/encrypt-and-mount.sh',
    'bin/setup-fetch-secrets.sh',
    'bin/ssh-hostkeys-collect.sh'
]
NDT_AND_CONSOLE = [
    'n-include=n_utils.cli:resolve_include',
    'n-include-all=n_utils.cli:resolve_all_includes',
    'cf-logs-to-cloudwatch=n_utils.cli:logs_to_cloudwatch',
    'logs-to-cloudwatch=n_utils.cli:logs_to_cloudwatch',
    'associate-eip=n_utils.cli:associate_eip',
    'signal-cf-status=n_utils.cli:signal_cf_status',
    'ec2-associate-eip=n_utils.cli:associate_eip'
]
NDT_ONLY = [
    'assume-role=n_utils.cli:assume_role',
    'list-file-to-json=n_utils.cli:list_file_to_json',
    'add-deployer-server=n_utils.cli:add_deployer_server',
    'yaml-to-json=n_utils.cli:yaml_to_json',
    'yaml-to-yaml=n_utils.cli:yaml_to_yaml',
    'json-to-yaml=n_utils.cli:json_to_yaml',
    'pytail=n_utils.cli:read_and_follow',
    'account-id=n_utils.cli:get_account_id',
    'cf-follow-logs=n_utils.cli:tail_stack_logs',
    'logs=n_utils.cli:get_logs',
    'cf-logical-id=n_utils.cli:logical_id',
    'cf-region=n_utils.cli:cf_region',
    'cf-get-parameter=n_utils.cli:get_parameter',
    'cf-signal-status=n_utils.cli:signal_cf_status',
    'cf-stack-name=n_utils.cli:stack_name',
    'cf-stack-id=n_utils.cli:stack_id',
    'ec2-clean-snapshots=n_utils.cli:clean_snapshots',
    'ec2-instance-id=n_utils.cli:instance_id',
    'ec2-region=n_utils.cli:ec2_region',
    'ec2-wait-for-metadata=n_utils.cli:wait_for_metadata',
    'region=n_utils.cli:ec2_region',
    'ec2-get-tag=n_utils.cli:tag',
    'ec2-get-userdata=n_utils.cli:get_userdata',
    'detach-volume=n_utils.cli:detach_volume',
    'mfa-add-token=n_utils.cli:cli_mfa_add_token',
    'mfa-delete-token=n_utils.cli:cli_mfa_delete_token',
    'mfa-code=n_utils.cli:cli_mfa_code',
    'mfa-backup=n_utils.cli:cli_mfa_backup_tokens',
    'mfa-qrcode=n_utils.cli:cli_mfa_to_qrcode',
    'cf-delete-stack=n_utils.cli:delete_stack',
    'setup-cli=n_utils.cli:setup_cli',
    'volume-from-snapshot=n_utils.cli:volume_from_snapshot',
    'snapshot-from-volume=n_utils.cli:snapshot_from_volume',
    'show-stack-params-and-outputs=n_utils.cli:show_stack_params_and_outputs',
    'get-images=n_utils.cli:cli_get_images',
    'promote-image=n_utils.cli:cli_promote_image',
    'share-to-another-region=n_utils.cli:cli_share_to_another_region',
    'register-private-dns=n_utils.cli:cli_register_private_dns',
    'interpolate-file=n_utils.cli:cli_interpolate_file',
    'ecr-ensure-repo=n_utils.cli:cli_ecr_ensure_repo',
    'ecr-repo-uri=n_utils.cli:cli_ecr_repo_uri',
    'upsert-cloudfront-records=n_utils.cli:cli_upsert_cloudfront_records',
    'create-stack=n_utils.cf_bootstrap:create_stack',
    'latest-snapshot=n_utils.volumes:latest_snapshot',
    'create-account=n_utils.cli:cli_create_account',
    'load-parameters=n_utils.cli:cli_load_parameters',
    'read-profile-expiry=n_utils.profile_util:cli_read_profile_expiry',
    'assumed-role-name=n_utils.cli:cli_assumed_role_name',
    'profile-to-env=n_utils.profile_util:profile_to_env',
    'profile-expiry-to-env=n_utils.profile_util:profile_expiry_to_env',
    'enable-profile=n_utils.profile_util:cli_enable_profile',
    'list-jobs=n_utils.cli:cli_list_jobs',
    'list-components=n_utils.cli:cli_list_components'
]
NDT_ONLY_SCRIPT = [
    'bake-docker.sh',
    'bake-image.sh',
    'deploy-stack.sh',
    'undeploy-stack.sh',
    'deploy-serverless.sh',
    'undeploy-serverless.sh',
    'deploy-cdk.sh',
    'undeploy-undeploy.sh',
    'deploy-terraform.sh',
    'undeploy-terraform.sh',
    'print-create-instructions.sh'
]
CONSOLE_ONLY = [
    'cf-update-stack=n_utils.cli:update_stack',
    'ndt=n_utils.ndt:ndt',
    'nitor-dt-register-complete=n_utils.project_util:ndt_register_complete',
    'nitor-dt-load-project-env=n_utils.project_util:load_project_env',
    'nitor-dt-enable-profile=n_utils.profile_util:cli_enable_profile'
]
CONSOLESCRIPTS = CONSOLE_ONLY + NDT_AND_CONSOLE
COMMAND_MAPPINGS = {}
for script in NDT_ONLY_SCRIPT:
    name = script
    value = "ndtscript"
    if name.endswith(".sh"):
        name = name[:-3]
        value = "ndtshell"
    COMMAND_MAPPINGS[name] = value
for script in NDT_AND_CONSOLE + NDT_ONLY:
    name, value = script.split("=")
    COMMAND_MAPPINGS[name] = value
