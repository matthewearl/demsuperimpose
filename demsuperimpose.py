# Copyright (c) 2023 Matthew Earl
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
#     The above copyright notice and this permission notice shall be included
#     in all copies or substantial portions of the Software.
# 
#     THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#     OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#     MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
#     NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#     DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#     OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
#     USE OR OTHER DEALINGS IN THE SOFTWARE.


import bisect
import dataclasses
import logging
import sys

import pydem
import messages


logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _BaseInfo:
    """Info extracted from a single pass through the demo"""
    models: list[str]
    max_entity_id: int

    @classmethod
    def process(cls, dem):
        server_info_seen = False
        models = None
        max_entity_id = None

        for block in dem.blocks:
            for msg in block.messages:
                if isinstance(msg, messages.ServerInfoMessage):
                    if server_info_seen:
                        raise Exception("multiple server infos")
                    models = msg.models_precache
                    server_info_seen = True
                if isinstance(msg, messages.EntityUpdateMessage):
                    if max_entity_id is None or max_entity_id < msg.num:
                        max_entity_id = msg.num
        return cls(models, max_entity_id)


@dataclasses.dataclass
class _GhostInfo:
    """A parsed demo with enough information to superimpose a ghost"""
    models: list[str]
    entity_baseline: messages.SpawnBaselineMessage
    entity_updates: list[messages.EntityUpdateMessage]
    times: list[float]

    @classmethod
    def process(cls, dem):
        server_info_seen = False
        view_entity_id = None
        models = None
        time = None
        entity_baseline = None
        times = []
        entity_updates = []

        for block in dem.blocks:
            for msg in block.messages:
                if isinstance(msg, messages.ServerInfoMessage):
                    if server_info_seen:
                        raise Exception("multiple server infos")
                    models = msg.models_precache
                    server_info_seen = True

                if isinstance(msg, messages.SetViewMessage):
                    view_entity_id = msg.viewentity_id

                if isinstance(msg, messages.SpawnBaselineMessage):
                    if view_entity_id is None:
                        raise Exception("baseline received before set view")
                    if msg.entity_num == view_entity_id:
                        entity_baseline = msg

                if isinstance(msg, messages.TimeMessage):
                    if entity_baseline is None:
                        raise Exception("time received before entity baseline")
                    time = msg.time

                if isinstance(msg, messages.EntityUpdateMessage):
                    if msg.num == view_entity_id:
                        if time is None:
                            raise Exception("entity update received without "
                                            "time")
                        entity_updates.append(msg)
                        times.append(time)
                        time = None

        if entity_baseline is None:
            raise Exception("no view entity baseline")

        return cls(models, entity_baseline, entity_updates, times)


def _main():
    logging.basicConfig(level=logging.INFO)
    fnames = sys.argv[1:]

    # Parse demos.
    logger.info('parsing base demo')
    base_dem = pydem.parse_demo(fnames[0])
    base_info = _BaseInfo.process(base_dem)
    logger.info('parsing ghost demos')
    ghost_infos = [
        _GhostInfo.process(pydem.parse_demo(fname))
        for fname in fnames[1:]
    ]

    # Construct mappings for model numbers.
    logger.info('converting demo')
    models_list = (
        [base_info.models]
        + [ghost_info.models for ghost_info in ghost_infos]
    )
    new_model_dict = {}
    for models in models_list:
        for model_name in models:
            if model_name not in new_model_dict:
                new_model_dict[model_name] = len(new_model_dict) + 1

    # Re-write the original demo.
    new_blocks = []
    for block in base_dem.blocks:
        new_messages = []

        # Convert model numbers to the new numbers.
        for msg in block.messages:
            if isinstance(msg, (messages.SpawnStaticMessage,
                                messages.SpawnBaselineMessage,
                                messages.EntityUpdateMessage)):
                if msg.modelindex is None:
                    model_num = None
                else:
                    model_num = new_model_dict[
                        base_info.models[msg.modelindex - 1]
                    ]
                new_messages.append(dataclasses.replace(
                    msg,
                    modelindex=model_num
                ))
            else:
                new_messages.append(msg)

        # Add baselines onto baseline block.
        if any(isinstance(msg, messages.SpawnBaselineMessage)
                for msg in block.messages):
            for idx, ghost_info in enumerate(ghost_infos):
                entity_num = idx + 1 + base_info.max_entity_id
                baseline = ghost_info.entity_baseline
                if baseline.modelindex is None:
                    model_num = None
                else:
                    model_num = new_model_dict[
                        ghost_info.models[baseline.modelindex - 1]
                    ]
                new_messages.append(
                    dataclasses.replace(
                        baseline,
                        entity_num=entity_num,
                        modelindex=model_num,
                    )
                )

        # Add update messages.
        if (block.messages
                and isinstance(block.messages[0], messages.TimeMessage)):
            time = block.messages[0].time
            for idx, ghost_info in enumerate(ghost_infos):

                time_idx = bisect.bisect(ghost_info.times, time) - 1
                if time_idx >= 0:
                    entity_num = idx + 1 + base_info.max_entity_id
                    update = ghost_info.entity_updates[time_idx]
                    if update.modelindex is None:
                        model_num = None
                    else:
                        model_num = new_model_dict[
                            ghost_info.models[update.modelindex - 1]
                        ]

                    flags = update.flags
                    if entity_num > 255:
                        flags |= messages.UpdateFlags.MOREBITS
                        flags |= messages.UpdateFlags.LONGENTITY
                    new_messages.append(
                        dataclasses.replace(
                            update,
                            num=entity_num,
                            modelindex=model_num,
                            flags=flags,
                        )
                    )

        new_blocks.append(dataclasses.replace(block, messages=new_messages))
    new_dem = dataclasses.replace(base_dem, blocks=new_blocks)
    logger.info('writing demo')
    with open('out.dem', 'wb') as f:
        new_dem.write(f)


if __name__ == "__main__":
    _main()
