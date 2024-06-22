# domainradar-input
Input subsystem with prefilters for DomainRadar

## Startup environment

The prefilter app now requires a startup environment to setup a connection to
kafka where we get the rest of the configuration.

The environment needs to define:
```bash
DOMAINRADAR_KAFKA_BROKER_URL=url to kafka broker
DOMAINRADAR_KAFKA_SECRETS_DIR=path to directory with authentication secrets
```
