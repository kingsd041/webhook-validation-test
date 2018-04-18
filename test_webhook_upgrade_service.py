from common_fixtures import *  # NOQA
from test_services_lb_balancer import create_environment_with_balancer_services
from test_services_links import create_environment_with_linked_services
import json

TEST_IMAGE_1 = 'cattle/test-agent'
TEST_IMAGE_1_tag_v7 = "v7"
TEST_IMAGE_1_tag_latest = "latest"
TEST_IMAGE_1_tag_v6 = "v6"
TEST_IMAGE_1_tag_v7_uuid = 'docker:' + TEST_IMAGE_1 + ':' + TEST_IMAGE_1_tag_v7
TEST_IMAGE_1_tag_latest_uuid = 'docker:' + TEST_IMAGE_1 + ':' + TEST_IMAGE_1_tag_latest

TEST_IMAGE_2 = 'busybox'
TEST_IMAGE_2_tag_1_28_0 = "1.28.0"
TEST_IMAGE_2_tag_latest = "latest"
TEST_IMAGE_2_tag_1_28_0_uuid = 'docker:' + TEST_IMAGE_2 + ':' + TEST_IMAGE_2_tag_1_28_0
TEST_IMAGE_2_tag_latest_uuid = 'docker:' + TEST_IMAGE_2 + ':' + TEST_IMAGE_2_tag_latest


HEALTH_CHECK_IMAGE_REPO = 'sangeetha/testhealthcheck'
HEALTH_CHECK_IMAGE_TAG_V2 = 'v2'
HEALTH_CHECK_IMAGE_TAG_LATEST = 'latest'
HEALTH_CHECK_IMAGE_UUID_V2 = 'docker:' + HEALTH_CHECK_IMAGE_REPO + ':' + HEALTH_CHECK_IMAGE_TAG_V2
HEALTH_CHECK_IMAGE_UUID_LATEST = 'docker:' + HEALTH_CHECK_IMAGE_REPO + ':' + HEALTH_CHECK_IMAGE_TAG_LATEST

SERVICE_WAIT_TIMEOUT = 180


def create_env_with_multiple_svc(client, scale_svc,
                                 launch_config, count):

    services = []
    # Create Environment
    env = create_env(client)

    # Create Service
    for i in range(0, count):
        random_name = random_str()
        service_name = random_name.replace("-", "")
        env_id = env.id
        service = client.create_service(name=service_name,
                                        stackId=env_id,
                                        launchConfig=launch_config,
                                        scale=scale_svc)

        service = client.wait_success(service)
        assert service.state == "inactive"
        services.append(service)

    for service in services:
        service = client.wait_success(service.activate(), SERVICE_WAIT_TIMEOUT)
        assert service.state == "active"
        assert service.scale == scale_svc

    return services, env


def create_and_execute_webhook(env_accountId, webhookName,
                               data_tag, post_tag, repo_name,
                               serviceSelector, batchSize=1,
                               intervalMillis=2,
                               payloadFormat='dockerhub'):

    data = {
        "name": webhookName,
        "driver": "serviceUpgrade",
        "serviceUpgradeConfig": {
            "addressType": "registry",
            "batchSize": batchSize,
            "intervalMillis": intervalMillis,
            "payloadFormat": payloadFormat,
            "serviceSelector": serviceSelector,
            "tag": data_tag,
            "type": "serviceUpgrade"
        }
    }

    post_data = {
        "push_data": {
            "tag": post_tag
        },
        "repository": {
            "repo_name": repo_name
        }
    }
    headers = {'Content-Type': 'application/json'}

    # Create Webhook
    resp = create_webhook(env_accountId, data)
    assert resp.status_code == 200
    assert resp.url is not None
    json_resp = json.loads(resp.content)
    webhook_url = json_resp["url"]
    webhook_id = json_resp["id"]

    print "Webhook is " + repr(webhook_url)
    print "Id is " + repr(webhook_id)

    # Execute Webhook and verify that the scale is incremented by
    # the amount specified
    wh_resp = requests.post(webhook_url, headers=headers,
                            data=json.dumps(post_data))
    assert wh_resp.status_code == 200
    time.sleep(1)
    return webhook_url, headers, data, post_data, webhook_id


def validate_exposed_port(client, service, public_port):
    con_list = get_service_container_list(client, service)
    assert len(con_list) == service.scale
    time.sleep(sleep_interval)
    for con in con_list:
        con_host = con.hosts[0]
        response = get_http_response(con_host, public_port, "/hostname")
        assert response == con.externalId[:12]


def test_webhook_upgrade(client):

    # Service Upgrade with label using latest tag in the webhook request

    launch_config = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1"}
                     }

    service, env = create_env_and_svc(client, launch_config)
    assert service.state == "inactive"
    service = client.wait_success(service.activate(), 90)
    assert service.state == "active"
    assert service.scale == 1

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest1',
                               data_tag=TEST_IMAGE_1_tag_latest,
                               post_tag=TEST_IMAGE_1_tag_latest,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)

    service = client.wait_success(service, 90)
    # service = wait_state(client, service, "active")
    # service = client.reload(service)
    assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_latest_uuid

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])


def test_webhook_upgrade_different_labels(client):

    # Multiple webhook requests with different image/tag with different labels

    launch_config1 = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1"}
                     }
    launch_config2 = {"imageUuid": TEST_IMAGE_2_tag_1_28_0_uuid,
                     "labels": {"key2": "value2"},
                     "stdin_open": "true",
                     "tty": "true"
                     }

    services1, env1 = create_env_with_multiple_svc(client, scale_svc=2,
                                                 launch_config=launch_config1,
                                                 count=2)
    services2, env2 = create_env_with_multiple_svc(client, scale_svc=2,
                                                 launch_config=launch_config2,
                                                 count=2)

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url1, headers1, data1, post_data1, webhook_id1 = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest2-1',
                               data_tag=TEST_IMAGE_1_tag_latest,
                               post_tag=TEST_IMAGE_1_tag_latest,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env1.accountId)
    for service1 in services1:
        service1 = client.wait_success(service1, 90)
        assert service1.launchConfig.imageUuid == TEST_IMAGE_1_tag_latest_uuid

    serviceSelector = {
                       "key2": "value2"
                      }
    webhook_url2, headers2, data2, post_data2, webhook_id2 = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest2-2',
                               data_tag=TEST_IMAGE_2_tag_latest,
                               post_tag=TEST_IMAGE_2_tag_latest,
                               repo_name=TEST_IMAGE_2,
                               serviceSelector=serviceSelector,
                               env_accountId=env2.accountId)

    for service2 in services2:
        service2 = client.wait_success(service2, 90) 
        assert service2.launchConfig.imageUuid == TEST_IMAGE_2_tag_latest_uuid
    # Delete the Webhook
    delete_webhook_verify(env1.accountId, webhook_id1)
    delete_webhook_verify(env2.accountId, webhook_id2)

    delete_all(client, [env1,env2])


def test_webhook_upgrade_same_tag(client):

    # Service Upgrade with  tag in the webook request same as the tag in the pushed image

    launch_config = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1"}
                     }

    services, env = create_env_with_multiple_svc(client, scale_svc=3,
                                                 launch_config=launch_config,
                                                 count=3)
    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest3',
                               data_tag=TEST_IMAGE_1_tag_v7,
                               post_tag=TEST_IMAGE_1_tag_v7,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)
                               
    for service in services:
        service = client.wait_success(service, 90)
        assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_v7_uuid
        assert service.state == "active"

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])




def test_webhook_upgrade_modify_label(client):

    # Modification of labels

    launch_config = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1"}
                     }

    services, env = create_env_with_multiple_svc(client, scale_svc=2,
                                                 launch_config=launch_config,
                                                 count=2)

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest4',
                               data_tag=TEST_IMAGE_1_tag_latest,
                               post_tag=TEST_IMAGE_1_tag_latest,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)
    for service in services:
        # service = client.wait_success(service, 90)
        service = wait_state(client, service, "active")
        assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_latest_uuid
        assert service.state == "active"

    # Modify the label of the service
    
    inServiceStrategy = {}
    inServiceStrategy["launchConfig"] = {'labels': {'key1': "value2"},
                                         'imageUuid': TEST_IMAGE_1_tag_v7_uuid
                                         }
    
    # Modify the label and image of one of the services
    service = services[0].upgrade_action(inServiceStrategy=inServiceStrategy)
    service = client.wait_success(service, 180)
    assert service.state == "upgraded"
    service = service.finishupgrade()
    service = client.wait_success(service, 180)
    assert service.state == "active"
    
    # Execute Webhook and verify that the scale is incremented by
    # the amount specified
    wh_resp = requests.post(webhook_url, headers=headers,
                            data=json.dumps(post_data))
    assert wh_resp.status_code == 200
    time.sleep(1)

    # verify that the services whose label have been modified do not upgrade
    service = client.wait_success(service, 90)
    assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_v7_uuid

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])


def test_webhook_upgrade_loadbalancer_services(
        client, socat_containers):
    LB_IMAGE_TAG = 'v0.9.1'
    LB_IMAGE_REPO = 'rancher/lb-service-haproxy'
    port = "19900"

    service_scale = 2
    lb_scale = 1

    env, service, lb_service = create_environment_with_balancer_services(
        client, service_scale, lb_scale, port)
    inServiceStrategy = {}
    inServiceStrategy["launchConfig"] = {'labels': {'key1': "value1"},
                                        'imageUuid': lb_service.launchConfig.imageUuid,
                                        'ports': lb_service.launchConfig.ports
                                        }
    lb_service = lb_service.upgrade_action(inServiceStrategy=inServiceStrategy)
    lb_service = client.wait_success(lb_service, 180)
    assert lb_service.state == "upgraded"
    lb_service = lb_service.finishupgrade()
    lb_service = client.wait_success(lb_service, 180)
    assert lb_service.state == "active"
    validate_lb_service(client, lb_service, port, [service])

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest5',
                               data_tag=LB_IMAGE_TAG,
                               post_tag=LB_IMAGE_TAG,
                               repo_name='rancher/lb-service-haproxy',
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)


    # verify that the services whose label have been modified do not upgrade
    lb_service = client.wait_success(lb_service, 90)
    validate_lb_service(client, lb_service, port, [service])
    assert lb_service.launchConfig.imageUuid == 'docker:' + LB_IMAGE_REPO + ":" + LB_IMAGE_TAG
    delete_all(client, [env])

def test_webhook_upgrade_global_service(client):

    # Upgrade services with exposed ports with the scale 
    # same as the number of hosts in the setup

    launch_config = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1",
                                "io.rancher.scheduler.global": "true"}}

    service, env = create_env_and_svc(
        client, launch_config, scale=None)

    service = client.wait_success(service.activate(), 90)

    assert service.state == "active"

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest6',
                               data_tag=TEST_IMAGE_1_tag_latest,
                               post_tag=TEST_IMAGE_1_tag_latest,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)

    service = client.wait_success(service, 90)

    assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_latest_uuid

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])


def test_webhook_upgrade_expose_port(client):

    # Upgrade services with exposed ports with 
    # the scale same as the number of hosts in the setup
    public_port = 19901
    private_port = 3000
    port_map = str(public_port)+":" + str(private_port)+ "/tcp"
    launch_config = {"imageUuid": TEST_IMAGE_1_tag_v7_uuid,
                     "labels": {"key1": "value1"},
                     "ports": port_map}

    services, env = create_env_with_multiple_svc(client, scale_svc=1,
                                                 launch_config=launch_config,
                                                 count=1)


    for service in services:
        assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_v7_uuid
        assert service.state == "active"
        validate_exposed_port(client, service, public_port)

    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest7',
                               data_tag=TEST_IMAGE_1_tag_latest,
                               post_tag=TEST_IMAGE_1_tag_latest,
                               repo_name=TEST_IMAGE_1,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)
    
    for service in services:
        # service = client.wait_success(service, 90)
        service = wait_state(client, service, "active")
        assert service.launchConfig.imageUuid == TEST_IMAGE_1_tag_latest_uuid
        assert service.state == "active"
        validate_exposed_port(client, service, public_port)

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])


def test_webhook_upgrade_links(client):

    # Upgrade services with exposed ports with the scale same as the number of hosts in the setup

    port = "19902"

    service_scale = 1
    consumed_service_scale = 2

    # Create few services with exposed ports
    env, service, consumed_service = create_environment_with_linked_services(
        client, service_scale, consumed_service_scale, port)

    validate_linked_service(client, service, [consumed_service], port,
                            linkName="mylink")
    validate_linked_service(client, service, [consumed_service], port,
                            linkName="mylink"+"."+RANCHER_FQDN)

    # Modify the label of the service
    inServiceStrategy = {}
    inServiceStrategy["launchConfig"] = {'labels': {'key1': "value1"},
                                         'imageUuid': 'docker:kingsd/testlbsd:v1'
                                         }
    consumed_service = consumed_service.upgrade_action(inServiceStrategy=inServiceStrategy)
    consumed_service = client.wait_success(consumed_service, 180)
    assert consumed_service.state == "upgraded"
    consumed_service = consumed_service.finishupgrade()
    consumed_service = client.wait_success(consumed_service, 180)
    assert consumed_service.state == "active"
    assert consumed_service.launchConfig.imageUuid == 'docker:kingsd/testlbsd:v1'
    
    # Create webhook for services with that label
    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest8',
                               data_tag='latest',
                               post_tag='latest',
                               repo_name='kingsd/testlbsd',
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)

    consumed_service = client.wait_success(consumed_service, 90)

    validate_linked_service(client, service, [consumed_service], port,
                            linkName="mylink")
    validate_linked_service(client, service, [consumed_service], port,
                            linkName="mylink"+"."+RANCHER_FQDN)

    assert consumed_service.launchConfig.imageUuid == 'docker:kingsd/testlbsd:latest'

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])


def test_webhook_upgrade_healthcheck(client):

    # Upgrade health check enabled services

    # Create few health check enabled services 
    health_check = {"name": "check1", "responseTimeout": 2000,
                    "interval": 2000, "healthyThreshold": 2,
                    "unhealthyThreshold": 3}
    health_check["requestLine"] = "GET /name.html HTTP/1.0"
    health_check["port"] = 80


    launch_config = {"imageUuid": HEALTH_CHECK_IMAGE_UUID_V2,
                     "healthCheck": health_check,
                     "labels": {"key1": "value1"}
                     }
    services, env = create_env_with_multiple_svc(client, scale_svc=1,
                                                 launch_config=launch_config,
                                                 count=1)
    
    # Create webhook for services with that label
    serviceSelector = {
                       "key1": "value1"
                      }
    webhook_url, headers, data, post_data, webhook_id = \
                               create_and_execute_webhook(
                               webhookName='servicesupgradetest3',
                               data_tag=HEALTH_CHECK_IMAGE_TAG_LATEST,
                               post_tag=HEALTH_CHECK_IMAGE_TAG_LATEST,
                               repo_name=HEALTH_CHECK_IMAGE_REPO,
                               serviceSelector=serviceSelector,
                               env_accountId=env.accountId)
          
    # Verify the health check service                     
    for service in services:
        service = wait_state(client, service, "active")
        assert service.launchConfig.imageUuid == HEALTH_CHECK_IMAGE_UUID_LATEST
        assert service.state == "active"
        container_list = get_service_container_list(client, service)
        assert \
        len(container_list) == get_service_instance_count(client, service)
        for con in container_list:
            wait_for_condition(
                client, con,
                lambda x: x.healthState == 'healthy',
                lambda x: 'State is: ' + x.healthState)

    # Delete the Webhook
    delete_webhook_verify(env.accountId, webhook_id)

    delete_all(client, [env])

