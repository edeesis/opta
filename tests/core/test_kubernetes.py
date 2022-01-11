import datetime
from subprocess import DEVNULL, CompletedProcess

import pytz
from kubernetes.client import (
    ApiException,
    CoreV1Api,
    V1Event,
    V1EventList,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimList,
    V1Pod,
)
from kubernetes.watch import Watch
from pytest_mock import MockFixture

from opta.core.kubernetes import (
    configure_kubectl,
    delete_persistent_volume_claims,
    get_required_path_executables,
    list_persistent_volume_claims,
    tail_module_log,
    tail_namespace_events,
    tail_pod_log,
)
from opta.layer import Layer


class TestKubernetes:
    def test_azure_configure_kubectl(self, mocker: MockFixture) -> None:
        mocked_ensure_installed = mocker.patch("opta.core.kubernetes.ensure_installed")
        layer = mocker.Mock(spec=Layer)
        layer.parent = None
        layer.cloud = "azurerm"
        layer.name = "blah"
        layer.providers = {
            "azurerm": {
                "location": "centralus",
                "tenant_id": "blahbc17-blah-blah-blah-blah291d395b",
                "subscription_id": "blah99ae-blah-blah-blah-blahd2a04788",
            }
        }
        layer.root.return_value = layer
        layer.gen_providers.return_value = {
            "terraform": {
                "backend": {"azurerm": {"resource_group_name": "dummy_resource_group"}}
            },
            "provider": {
                "azurerm": {
                    "location": "centralus",
                    "tenant_id": "blahbc17-blah-blah-blah-blah291d395b",
                    "subscription_id": "blah99ae-blah-blah-blah-blahd2a04788",
                }
            },
        }
        mocked_terraform_output = mocker.patch(
            "opta.core.kubernetes.get_terraform_outputs",
            return_value={"k8s_cluster_name": "mocked_cluster_name"},
        )
        mocked_nice_run = mocker.patch("opta.core.kubernetes.nice_run",)

        configure_kubectl(layer)

        mocked_terraform_output.assert_called_once_with(layer)
        mocked_ensure_installed.assert_has_calls(
            [mocker.call("kubectl"), mocker.call("az")]
        )
        mocked_nice_run.assert_has_calls(
            [
                mocker.call(
                    [
                        "az",
                        "aks",
                        "get-credentials",
                        "--resource-group",
                        "dummy_resource_group",
                        "--name",
                        "mocked_cluster_name",
                        "--admin",
                        "--overwrite-existing",
                    ],
                    stdout=DEVNULL,
                    check=True,
                ),
            ]
        )

    def test_configure_kubectl(self, mocker: MockFixture) -> None:
        mocked_ensure_installed = mocker.patch("opta.core.kubernetes.ensure_installed")
        mocked_nice_run = mocker.patch(
            "opta.core.kubernetes.nice_run",
            side_effect=[
                CompletedProcess(None, 0, "blah".encode("utf-8")),  # type: ignore
            ],
        )
        mock_aws_client_instance = mocker.Mock()
        mock_aws_get_caller_identity = {
            "UserId": "mocked_user_id:jd@runx.dev",
            "Account": "111111111111",
            "Arn": "mocked_arn",
        }
        mock_sts_client = mocker.patch(
            "opta.core.kubernetes.boto3.client", return_value=mock_aws_client_instance
        )
        mock_aws_client_instance.get_caller_identity.return_value = (
            mock_aws_get_caller_identity
        )

        layer = mocker.Mock(spec=Layer)
        layer.parent = None
        layer.cloud = "aws"
        layer.name = "blah"
        layer.providers = {"aws": {"region": "us-east-1", "account_id": "111111111111"}}
        layer.root.return_value = layer
        mocked_terraform_output = mocker.patch(
            "opta.core.kubernetes.get_terraform_outputs",
            return_value={"k8s_cluster_name": "mocked_cluster_name"},
        )

        configure_kubectl(layer)

        mock_sts_client.assert_called_once_with("sts")
        mocked_terraform_output.assert_called_once_with(layer)
        mocked_ensure_installed.assert_has_calls(
            [mocker.call("kubectl"), mocker.call("aws")]
        )
        mocked_nice_run.assert_has_calls(
            [
                # TODO: nsarupri -> change the AWS to Boto
                mocker.call(
                    [
                        "aws",
                        "eks",
                        "update-kubeconfig",
                        "--name",
                        "mocked_cluster_name",
                        "--region",
                        "us-east-1",
                    ],
                    stdout=DEVNULL,
                    check=True,
                ),
            ]
        )

    def test_get_required_path_executables(self) -> None:
        assert len(get_required_path_executables("local")) == 1

        aws_deps = get_required_path_executables("aws")
        assert len(aws_deps) == 2
        for dep in ["aws", "kubectl"]:
            assert dep in aws_deps

    def test_tail_module_log(self, mocker: MockFixture) -> None:
        base_start_time_timestamp = datetime.datetime.utcnow().timestamp()
        mocked_load_kube_config = mocker.patch("opta.core.kubernetes.load_kube_config")
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocked_core_v1_api_call = mocker.patch(
            "opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api
        )
        mocked_watch = mocker.Mock(spec=Watch)
        mocked_watch_call = mocker.patch(
            "opta.core.kubernetes.Watch", return_value=mocked_watch
        )
        layer = mocker.Mock(spec=Layer)
        layer.name = "mocked_layer"
        layer.parent = None
        layer.providers = {"aws": {"region": "us-east-1", "account_id": "111111111111"}}
        mocked_pod_1 = mocker.Mock(spec=V1Pod)
        mocked_pod_1.metadata = mocker.Mock()
        mocked_pod_1.metadata.name = "pod1"
        mocked_pod_1.metadata.creation_timestamp = datetime.datetime.fromtimestamp(
            base_start_time_timestamp + 10000
        ).replace(tzinfo=pytz.UTC)
        mocked_event_1 = {"object": mocked_pod_1}
        thread_1 = mocker.Mock()
        mocked_pod_2 = mocker.Mock(spec=V1Pod)
        mocked_pod_2.metadata = mocker.Mock()
        mocked_pod_2.metadata.name = "pod2"
        mocked_pod_2.metadata.creation_timestamp = datetime.datetime.fromtimestamp(
            base_start_time_timestamp + 10000
        ).replace(tzinfo=pytz.UTC)
        mocked_event_2 = {"object": mocked_pod_2}
        thread_2 = mocker.Mock()
        mocked_watch.stream.return_value = [mocked_event_1, mocked_event_2]

        mocked_thread = mocker.patch(
            "opta.core.kubernetes.Thread", side_effect=[thread_1, thread_2]
        )

        tail_module_log(layer, "mocked_module_name", since_seconds=3, start_color_idx=2)
        mocked_watch_call.assert_called_once_with()
        mocked_core_v1_api_call.assert_called_once_with()
        mocked_load_kube_config.assert_called_once_with()
        thread_1.start.assert_called_once_with()
        thread_2.start.assert_called_once_with()
        mocked_thread.assert_has_calls(
            [
                mocker.call(
                    target=tail_pod_log,
                    args=("mocked_layer", mocked_pod_1, 2, 3),
                    daemon=True,
                ),
                mocker.call(
                    target=tail_pod_log,
                    args=("mocked_layer", mocked_pod_2, 3, 3),
                    daemon=True,
                ),
            ]
        )

    def test_tail_module_log_mute_old_pod_logs(self, mocker: MockFixture) -> None:
        base_start_time_timestamp = datetime.datetime.utcnow().timestamp()
        mocked_load_kube_config = mocker.patch("opta.core.kubernetes.load_kube_config")
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocked_core_v1_api_call = mocker.patch(
            "opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api
        )
        mocked_watch = mocker.Mock(spec=Watch)
        mocked_watch_call = mocker.patch(
            "opta.core.kubernetes.Watch", return_value=mocked_watch
        )
        layer = mocker.Mock(spec=Layer)
        layer.name = "mocked_layer"
        layer.parent = None
        layer.providers = {"aws": {"region": "us-east-1", "account_id": "111111111111"}}
        mocked_pod_1 = mocker.Mock(spec=V1Pod)
        mocked_pod_1.metadata = mocker.Mock()
        mocked_pod_1.metadata.name = "pod1"
        mocked_pod_1.metadata.creation_timestamp = datetime.datetime.fromtimestamp(
            base_start_time_timestamp + 10000
        ).replace(tzinfo=pytz.UTC)
        mocked_event_1 = {"object": mocked_pod_1}
        thread_1 = mocker.Mock()
        mocked_pod_2 = mocker.Mock(spec=V1Pod)
        mocked_pod_2.metadata = mocker.Mock()
        mocked_pod_2.metadata.name = "pod2"
        mocked_pod_2.metadata.creation_timestamp = datetime.datetime.fromtimestamp(
            base_start_time_timestamp - 10000
        ).replace(tzinfo=pytz.UTC)
        mocked_event_2 = {"object": mocked_pod_2}
        thread_2 = mocker.Mock()
        mocked_watch.stream.return_value = [mocked_event_1, mocked_event_2]

        mocked_thread = mocker.patch(
            "opta.core.kubernetes.Thread", side_effect=[thread_1, thread_2]
        )

        tail_module_log(layer, "mocked_module_name", since_seconds=3, start_color_idx=2)
        mocked_watch_call.assert_called_once_with()
        mocked_core_v1_api_call.assert_called_once_with()
        mocked_load_kube_config.assert_called_once_with()
        thread_1.start.assert_called_once_with()
        """
        IMPORTANT:
        POD#1 (New Pod) (Logs tailed)
        POD#2 (Old Pod) (Logs Muted)
        Hence the tail_pod_log method is only called for POD#1 and not POD#2
        """
        mocked_thread.assert_has_calls(
            [
                mocker.call(
                    target=tail_pod_log,
                    args=("mocked_layer", mocked_pod_1, 2, 3),
                    daemon=True,
                )
            ]
        )

    def test_tail_pod_log(self, mocker: MockFixture) -> None:
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocked_core_v1_api_call = mocker.patch(
            "opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api
        )
        mocked_watch = mocker.Mock(spec=Watch)
        mocked_watch_call = mocker.patch(
            "opta.core.kubernetes.Watch", return_value=mocked_watch
        )
        mocked_watch.stream.side_effect = [
            "hello_world",
            ApiException(status=400),
            ApiException(status=400),
            ApiException(status=400),
            Exception(),
            ApiException(status=400),
        ]
        mocked_pod = mocker.Mock(spec=V1Pod)
        mocked_pod.metadata = mocker.Mock()
        mocked_pod.metadata.name = "pod1"
        mocked_time = mocker.patch("opta.core.kubernetes.time")

        tail_pod_log("mocked_namespace", mocked_pod, 2, 3)

        mocked_watch_call.assert_called_once_with()
        mocked_core_v1_api_call.assert_called_once_with()
        mocked_time.sleep.assert_has_calls(
            [
                mocker.call(0),
                mocker.call(1),
                mocker.call(2),
                mocker.call(3),
                mocker.call(4),
                mocker.call(5),
                mocker.call(6),
                mocker.call(7),
                mocker.call(8),
                mocker.call(9),
                mocker.call(10),
                mocker.call(11),
                mocker.call(12),
                mocker.call(13),
                mocker.call(14),
            ]
        )
        assert mocked_time.sleep.call_count == 15

        # Tailing should not retry upon encountering a 404 API exception.
        mocked_watch.stream.side_effect = [
            "hello_world",
            ApiException(status=400),
            ApiException(status=404),
        ]
        mocked_time = mocker.patch("opta.core.kubernetes.time")
        tail_pod_log("mocked_namespace", mocked_pod, 2, 3)
        assert mocked_time.sleep.call_count == 1

    def test_tail_namespace_events(self, mocker: MockFixture) -> None:
        mocker.patch("opta.core.kubernetes.load_kube_config")
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocked_core_v1_api_call = mocker.patch(
            "opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api
        )
        mocked_watch = mocker.Mock(spec=Watch)
        mocked_watch_call = mocker.patch(
            "opta.core.kubernetes.Watch", return_value=mocked_watch
        )
        layer = mocker.Mock(spec=Layer)
        layer.name = "mocked_layer"
        layer.parent = None
        layer.providers = {"aws": {"region": "us-east-1", "account_id": "111111111111"}}
        mocked_old_events = mocker.Mock(spec=V1EventList)
        mocked_event_1 = mocker.Mock(spec=V1Event)
        mocked_event_1.last_timestamp = datetime.datetime.now(
            pytz.utc
        ) - datetime.timedelta(seconds=1)
        mocked_event_1.message = "blah1"
        mocked_event_2 = mocker.Mock(spec=V1Event)
        mocked_event_2.last_timestamp = datetime.datetime.now(
            pytz.utc
        ) - datetime.timedelta(seconds=100)
        mocked_event_2.message = "blah2"
        mocked_event_3 = mocker.Mock(spec=V1Event)
        mocked_event_3.last_timestamp = datetime.datetime.now(
            pytz.utc
        ) - datetime.timedelta(seconds=10)
        mocked_event_3.message = "blah3"
        mocked_old_events.items = [mocked_event_1, mocked_event_2, mocked_event_3]
        mocked_core_v1_api.list_namespaced_event.return_value = mocked_old_events

        mocked_event_4 = mocker.Mock(spec=V1Event)
        mocked_event_4.last_timestamp = datetime.datetime.now(
            pytz.utc
        ) - datetime.timedelta(seconds=100)
        mocked_event_4.message = "blah2"
        mocked_event_5 = mocker.Mock(spec=V1Event)
        mocked_event_5.last_timestamp = datetime.datetime.now(
            pytz.utc
        ) - datetime.timedelta(seconds=10)
        mocked_event_5.message = "blah3"

        mocked_watch.stream.side_effect = [
            [{"object": mocked_event_4}],
            [{"object": mocked_event_5}],
            ApiException(status=400),
            ApiException(status=400),
            ApiException(status=400),
            ApiException(status=400),
            ApiException(status=400),
        ]
        mocked_time = mocker.patch("opta.core.kubernetes.time")
        start_time = datetime.datetime.now(pytz.utc) - datetime.timedelta(seconds=2)

        tail_namespace_events(layer, start_time, 3)

        mocked_core_v1_api.list_namespaced_event.assert_called_once_with(
            namespace="mocked_layer"
        )
        mocked_watch_call.assert_called_once_with()
        mocked_core_v1_api_call.assert_called_once_with()
        mocked_time.sleep.assert_has_calls(
            [
                mocker.call(1),
                mocker.call(2),
                mocker.call(4),
                mocker.call(8),
                mocker.call(16),
            ]
        )

    def test_list_persistent_volume_claims(self, mocker: MockFixture) -> None:
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocker.patch("opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api)
        mocker.patch("opta.core.kubernetes.load_kube_config")
        mocked_claim_opta = mocker.Mock(spec=V1PersistentVolumeClaim)
        mocked_claim_opta.metadata = mocker.Mock()
        mocked_claim_opta.metadata.name = "opta-claim-0"

        mocked_claim_non_opta = mocker.Mock(spec=V1PersistentVolumeClaim)
        mocked_claim_non_opta.metadata = mocker.Mock()
        mocked_claim_non_opta.metadata.name = "my-org-claim-0"

        mocked_claim_list = mocker.Mock(spec=V1PersistentVolumeClaimList)
        mocked_claim_list.items = [mocked_claim_opta, mocked_claim_non_opta]

        mocked_core_v1_api.list_persistent_volume_claim_for_all_namespaces.return_value = (
            mocked_claim_list
        )
        mocked_core_v1_api.list_namespaced_persistent_volume_claim.return_value = (
            mocked_claim_list
        )

        # call with no parameter, expect all_namespaces method called
        results = list_persistent_volume_claims()
        mocked_core_v1_api.list_persistent_volume_claim_for_all_namespaces.assert_called_once_with()
        assert len(results) == 2

        # call with namespace, expect namespaced method called
        results = list_persistent_volume_claims(namespace="hello")
        mocked_core_v1_api.list_namespaced_persistent_volume_claim.assert_called_once_with(
            "hello"
        )

        # check opta_managed filtering works
        results = list_persistent_volume_claims(opta_managed=True)
        assert len(results) == 1

    def test_delete_persistent_volume_claims(self, mocker: MockFixture) -> None:
        mocked_core_v1_api = mocker.Mock(spec=CoreV1Api)
        mocker.patch("opta.core.kubernetes.CoreV1Api", return_value=mocked_core_v1_api)
        mocker.patch("opta.core.kubernetes.load_kube_config")
        mocked_claim_opta1 = mocker.Mock(spec=V1PersistentVolumeClaim)
        mocked_claim_opta1.metadata = mocker.Mock()
        mocked_claim_opta1.metadata.name = "opta-claim-1"

        mocked_claim_opta2 = mocker.Mock(spec=V1PersistentVolumeClaim)
        mocked_claim_opta2.metadata = mocker.Mock()
        mocked_claim_opta2.metadata.name = "opta-claim-2"

        mocked_list_persistent_volume_claims = mocker.patch(
            "opta.core.kubernetes.list_persistent_volume_claims",
            return_value=[mocked_claim_opta1, mocked_claim_opta2],
        )

        # call with no parameter, expect list PVC method called and 2 delete PVC calls
        namespace = "hello"
        delete_persistent_volume_claims(
            namespace=namespace, opta_managed=True, async_req=True
        )
        mocked_list_persistent_volume_claims.assert_called_once_with(
            namespace="hello", opta_managed=True
        )

        mocked_core_v1_api.delete_collection_namespaced_persistent_volume_claim.assert_has_calls(
            [
                mocker.call(
                    namespace="hello",
                    field_selector="metadata.name=opta-claim-1",
                    async_req=True,
                    body=mocker.ANY,
                ),
                mocker.call(
                    namespace="hello",
                    field_selector="metadata.name=opta-claim-2",
                    async_req=True,
                    body=mocker.ANY,
                ),
            ]
        )

        # pv are automatically deleted by k8s after deleting the claim, not by opta
        mocked_core_v1_api.assert_not_called()
