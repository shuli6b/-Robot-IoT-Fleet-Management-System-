import asyncio
import logging
from amqtt.broker import Broker

logger = logging.getLogger(__name__)

config = {
    'listeners': {
        'default': {
            'type': 'tcp',
            'bind': '0.0.0.0:1883',
        }
    },
    'sys_interval': 10,
    'plugins': [
        'amqtt.plugins.authentication.AnonymousAuthPlugin',
    ],
    'auth': {
        'allow-anonymous': True
    }
}

async def broker_coro():
    broker = Broker(config)
    await broker.start()
    
if __name__ == '__main__':
    formatter = "[%(asctime)s] :: %(levelname)s :: %(name)s :: %(message)s"
    logging.basicConfig(level=logging.INFO, format=formatter)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(broker_coro())
    loop.run_forever()
