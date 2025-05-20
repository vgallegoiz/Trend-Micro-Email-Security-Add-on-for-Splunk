import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import import_declare_test
from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

from TrendMicroObject import TrendMicro

ADDON_NAME = "trendmicro_ddei"

def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")

def get_account_info(session_key: str, account_name: str):
    cfm = conf_manager.ConfManager(
        session_key,
        ADDON_NAME,
        realm=f"__REST_CREDENTIAL__#{ADDON_NAME}#configs/conf-trendmicro_ddei_account",
    )
    account_conf_file = cfm.get_conf("trendmicro_ddei_account")
    api_key = account_conf_file.get(account_name).get("api_key")
    url = account_conf_file.get(account_name).get("url")
    username = account_conf_file.get(account_name).get("username")
    return api_key, url, username

class Input(smi.Script):
    def __init__(self):
        super().__init__()

    def create_or_return_checkpointer(self):
        session_key = self._input_definition.metadata["session_key"]
        self.checkpoint = checkpointer.KVStoreCheckpointer(f"{ADDON_NAME}_checkpointer2", session_key, ADDON_NAME, )

    def get_scheme(self):
        scheme = smi.Scheme("trendmicro_ddei")
        scheme.description = "trendmicro_ddei input"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        #scheme.add_argument(smi.Argument("name", title="Name", description="Name", required_on_create=True))        
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        return

    def stream_events(self, inputs: smi.InputDefinition, event_writer: smi.EventWriter):
        # inputs.inputs is a Python dictionary object like:
        # {
        #   "trendmicro_ddei_account://<input_name>": {
        #     "account": "<account_name>",
        #     "disabled": "0",
        #     "host": "$decideOnStartup",
        #     "index": "<index_name>",
        #     "interval": "<interval_value>",
        #     "python.version": "python3",
        #   },
        # }
        for input_name, input_item in inputs.inputs.items():
            normalized_input_name = input_name.split("/")[-1]
            logger = logger_for_input(normalized_input_name)

            try:
                session_key = self._input_definition.metadata["session_key"]
                log_level = conf_manager.get_log_level(
                    logger=logger,
                    session_key=session_key,
                    app_name=ADDON_NAME,
                    conf_name=f"{ADDON_NAME}_settings",
                )
                logger.setLevel(log_level)
                log.modular_input_start(logger, normalized_input_name)
                logger.info("Starting checkpointer TrendMicro DDEI")
                self.create_or_return_checkpointer()
                
                logger.info("getting account info")
                api_key, url, username = get_account_info(session_key, input_item.get("account"))
                index = input_item.get("index")
                input_types = input_item.get("input_type", "").split('|')
                input_type_log = ",".join(input_types)
                logger.info(f"input_type={input_type_log} index={index}, {normalized_input_name}")
                
                logger.info(f"Initializing TrendMicro DDEI: input_name={normalized_input_name}")
                trend_micro = TrendMicro(url, username, api_key)

                if "policy_event_logs" in input_types:
                    try:
                        logger.info(f"Getting checkpointer to policy_event_logs to input_name={normalized_input_name}")
                        start_iso = ""
                        try:
                            last_checkpoint = self.checkpoint.get(f"{normalized_input_name}_policy_event_logs")
                        except Exception as e:
                            logger.warning(f"Error reading checkpoint: {e}")
                            last_checkpoint = None
                        if not last_checkpoint:
                            logger.info("There is no checkpointer on policy_event_logs")
                            start = datetime.now(timezone.utc)
                            start_iso = start.strftime('%Y-%m-%dT%H:%M:%SZ')
                        else: 
                            start_iso = last_checkpoint
                        end = datetime.now(timezone.utc)
                        end_iso = end.strftime('%Y-%m-%dT%H:%M:%SZ')
                        try:
                            response = trend_micro.list_policy_event_logs(start_iso, end_iso, "")
                        except Exception as e:
                            logger.info(f"Fallo en el response {e}")
                            exit()
                        now = datetime.now().timestamp()
                        if response.status_code ==  200:
                            try:
                                response_data = response.json()
                            except Exception as e:
                                logger.error("No hay JSON")
                                raise Exception
                            for item in response_data['logs']:
                                item.update({'input_name': normalized_input_name})
                                event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:policy_event_logs", index=index, source=normalized_input_name)
                                event.stanza = input_name
                                event.data = json.dumps(item, ensure_ascii=False, default=str)
                                event_writer.write_event(event)
                            i = 1
                            while response_data.get('nextToken') and response.status_code == 200: # If there is a next token, call list_policy_events until there is not. 
                                logger.info(f"There is a next token {i}")
                                next_token = response_data['nextToken']
                                try:
                                    response = trend_micro.list_policy_event_logs(start_iso, end_iso, next_token)
                                    if response.status_code == 200:
                                        try:
                                            response_data = response.json()
                                        except Exception as e:
                                            print(f"Error decoding JSON: {e}")
                                            print("Raw JSON content:", response.text)
                                            exit()
                                        for item in response_data['logs']:
                                            item.update({'input_name': normalized_input_name})
                                            event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:policy_event_logs", index=index, source=normalized_input_name)
                                            event.stanza = input_name
                                            event.data = json.dumps(item, ensure_ascii=False, default=str)
                                            event_writer.write_event(event)
                                    elif response.status_code == 204:
                                        logger.info("Received correctly but no logs are available to ingest after the token")
                                        break
                                    else:
                                        logger.info(f"Response code: {response.status_code} after the token")
                                        break
                                    i += 1
                                except Exception as e:
                                    logger.info(f"Fallo en el response {e}")
                            logger.info("policy_event_logs successfully ingested.")
                        elif response.status_code == 204:
                            logger.info("Received correctly but no more logs are available to ingest")
                        else:
                            logger.info(f"Response code: {response.status_code}")
                        self.checkpoint.update(f"{normalized_input_name}_policy_event_logs", end_iso)
                        logger.info(f"Checkpointer on {normalized_input_name} and sourcetyepe policy_event_logs updated")
                    except Exception as e:
                        logger.info("Get response failed")
                        log.log_exception(logger, e, exc_label=ADDON_NAME ,msg_before=f'input_name={normalized_input_name}')
                
                if "mail_tracking_logs_accepted_traffic" in input_types:
                    try:
                        logger.info(f"Getting checkpointer to mail_tracking_logs_accepted_traffic to input_name={normalized_input_name}")
                        start_iso = ""
                        try:
                            last_checkpoint = self.checkpoint.get(f"{normalized_input_name}_mail_tracking_logs_accepted_traffic")
                        except Exception as e:
                            logger.warning(f"Error reading checkpoint: {e}")
                            last_checkpoint = None
                        if not last_checkpoint:
                            logger.info("There is no checkpointer on mail_tracking_logs_accepted_traffic")
                            start = datetime.now(timezone.utc)
                            start_iso = start.strftime('%Y-%m-%dT%H:%M:%SZ')

                        else:
                            start_iso = last_checkpoint
                        end = datetime.now(timezone.utc)
                        end_iso = end.strftime('%Y-%m-%dT%H:%M:%SZ')
                        try:
                            response = trend_micro.list_mail_tracking_logs("accepted_traffic", start_iso, end_iso, "")
                        except Exception as e:
                            logger.info(f"Fallo en el response {e}")
                            exit()
                        now = datetime.now().timestamp()
                        if response.status_code == 200:
                            try:
                                response_data = response.json()
                            except Exception as e:
                                logger.error("No hay JSON")
                                raise Exception
                            for item in response_data['logs']:
                                item.update({'input_name': normalized_input_name})
                                event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:mail_tracking_logs_accepted_traffic", index=index, source=normalized_input_name)
                                event.stanza = input_name
                                event.data = json.dumps(item, ensure_ascii=False, default=str)
                                event_writer.write_event(event)
                            i = 1
                            while response_data.get('nextToken') and response.status_code == 200:
                                logger.info(f"There is a next token {i}")
                                next_token = response_data['nextToken']
                                try:
                                    response = trend_micro.list_mail_tracking_logs("accepted_traffic", start_iso, end_iso, next_token)
                                    if response.status_code == 200:
                                        try:
                                            response_data = response.json()
                                        except Exception as e:
                                            print(f"Error decoding JSON: {e}")
                                            print("Raw JSON content:", response.text)
                                            exit()
                                        for item in response_data['logs']:
                                            item.update({'input_name': normalized_input_name})
                                            event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:mail_tracking_logs_accepted_traffic", index=index, source=normalized_input_name)
                                            event.stanza = input_name
                                            event.data = json.dumps(item, ensure_ascii=False, default=str)
                                            event_writer.write_event(event)
                                    elif response.status_code == 204:
                                        logger.info("Received correctly but no logs are available to ingest after the token")
                                        break
                                    else:
                                        logger.info(f"Response code: {response.status_code} after the token")
                                        break
                                    i += 1
                                except Exception as e:
                                    logger.info(f"Fallo en el response {e}")
                            logger.info("mail_tracking_logs_accepted_traffic successfully ingested.")
                        elif response.status_code == 204:
                            logger.info("Received correctly but no more logs are available to ingest")
                        else:
                            logger.info(f"Response code: {response.status_code}")
                        self.checkpoint.update(f"{normalized_input_name}_mail_tracking_logs_accepted_traffic", end_iso)
                        logger.info(f"Checkpointer on {normalized_input_name} and sourcetyepe mail_tracking_logs_accepted_traffic updated")
                    except Exception as e:
                        logger.info("Get response failed")
                        log.log_exception(logger, e, exc_label=ADDON_NAME, msg_before=f'input_name={normalized_input_name}')


                if "mail_tracking_logs_blocked_traffic" in input_types:
                    try:
                        logger.info(f"Getting checkpointer to mail_tracking_logs_blocked_traffic to input_name={normalized_input_name}")
                        start_iso = ""
                        try:
                            last_checkpoint = self.checkpoint.get(f"{normalized_input_name}_mail_tracking_logs_blocked_traffic")
                        except Exception as e:
                            logger.warning(f"Error reading checkpoint: {e}")
                            last_checkpoint = None
                        if not last_checkpoint:
                            logger.info("There is no checkpointer on mail_tracking_logs_blocked_traffic")
                            start = datetime.now(timezone.utc)
                            start_iso = start.strftime('%Y-%m-%dT%H:%M:%SZ')
                        else:
                            start_iso = last_checkpoint
                        end = datetime.now(timezone.utc)
                        end_iso = end.strftime('%Y-%m-%dT%H:%M:%SZ')
                        try:
                            response = trend_micro.list_mail_tracking_logs("blocked_traffic", start_iso, end_iso, "")
                        except Exception as e:
                            logger.info(f"Fallo en el response {e}")
                            exit()
                        now = datetime.now().timestamp()
                        if response.status_code == 200:
                            try:
                                response_data = response.json()
                            except Exception as e:
                                logger.error("No hay JSON")
                                raise Exception
                            for item in response_data['logs']:
                                item.update({'input_name': normalized_input_name})
                                event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:mail_tracking_logs_blocked_traffic", index=index, source=normalized_input_name)
                                event.stanza = input_name
                                event.data = json.dumps(item, ensure_ascii=False, default=str)
                                event_writer.write_event(event)
                            i = 1
                            while response_data.get('nextToken') and response.status_code == 200:
                                logger.info(f"There is a next token {i}")
                                next_token = response_data['nextToken']
                                try:
                                    response = trend_micro.list_mail_tracking_logs("blocked_traffic", start_iso, end_iso, next_token)
                                    if response.status_code == 200:
                                        try:
                                            response_data = response.json()
                                        except Exception as e:
                                            print(f"Error decoding JSON: {e}")
                                            print("Raw JSON content:", response.text)
                                            exit()
                                        for item in response_data['logs']:
                                            item.update({'input_name': normalized_input_name})
                                            event = smi.Event(time="%.3f" % now, sourcetype="TrendMicroDDE:mail_tracking_logs_blocked_traffic", index=index, source=normalized_input_name)
                                            event.stanza = input_name
                                            event.data = json.dumps(item, ensure_ascii=False, default=str)
                                            event_writer.write_event(event)
                                    elif response.status_code == 204:
                                        logger.info("Received correctly but no logs are available to ingest after the token")
                                        break
                                    else:
                                        logger.info(f"Response code: {response.status_code} after the token")
                                        break
                                    i += 1
                                except Exception as e:
                                    logger.info(f"Fallo en el response {e}")
                            logger.info("mail_tracking_logs_blocked_traffic successfully ingested.")
                        elif response.status_code == 204:
                            logger.info("Received correctly but no more logs are available to ingest")
                        else:
                            logger.info(f"Response code: {response.status_code}")
                        self.checkpoint.update(f"{normalized_input_name}_mail_tracking_logs_blocked_traffic", end_iso)
                        logger.info(f"Checkpointer on {normalized_input_name} and sourcetyepe mail_tracking_logs_blocked_traffic updated")
                    except Exception as e:
                        logger.info("Get response failed")
                        log.log_exception(logger, e, exc_label=ADDON_NAME, msg_before=f'input_name={normalized_input_name}')

            except Exception as e:
                logger.info(f"Error during TrendMicro DDEI ingestion {e}")
                log.log_exception(logger, e, exc_label=ADDON_NAME, msg_before="Error during TrendMicro DDEI ingestion")

if __name__ == "__main__":
    exit_code = Input().run(sys.argv)
    sys.exit(exit_code)