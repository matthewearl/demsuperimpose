# Copyright (c) 2024 Matthew Earl
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


_MAX_SCOREBOARD = 16


@dataclasses.dataclass
class _BaseInfo:
    """Info extracted from a single pass through the demo"""
    models: list[str]
    max_entity_id: int
    max_clients: int
    first_non_client_entity_id: int

    @classmethod
    def process(cls, dem):
        server_info_seen = False
        models = None
        max_entity_id = None
        max_clients = None
        first_non_client_entity_id = None

        for block in dem.blocks:
            for msg in block.messages:
                if isinstance(msg, messages.ServerInfoMessage):
                    if server_info_seen:
                        raise Exception("multiple server infos")
                    models = msg.models_precache
                    server_info_seen = True
                    max_clients = msg.max_clients
                if (isinstance(msg, messages.EntityUpdateMessage)
                        and (max_entity_id is None or max_entity_id < msg.num)):
                    max_entity_id = msg.num

        for block in dem.blocks:
            for msg in block.messages:
                if (isinstance(msg, messages.EntityUpdateMessage)
                        and msg.num > max_clients
                        and (first_non_client_entity_id is None
                             or first_non_client_entity_id > msg.num)):
                    first_non_client_entity_id = msg.num

        return cls(models, max_entity_id, max_clients,
                   first_non_client_entity_id)


@dataclasses.dataclass
class _GhostInfo:
    """A parsed demo with enough information to superimpose a ghost"""
    models: list[str]
    entity_baseline: messages.SpawnBaselineMessage
    entity_updates: list[messages.EntityUpdateMessage]
    times: list[float]
    name: str
    color: int

    @classmethod
    def process_all(cls, dem):
        server_info_seen = False
        view_entity_id = None
        models = None
        time = None
        entity_baseline = None
        times = []
        entity_updates = []
        name = "name not set"
        color = 0

        for block in dem.blocks:
            for msg in block.messages:
                if isinstance(msg, messages.ServerInfoMessage):
                    if server_info_seen:
                        yield cls(models, entity_baseline, entity_updates,
                                  times, name, color)

                        server_info_seen = False
                        view_entity_id = None
                        models = None
                        time = None
                        entity_baseline = None
                        times = []
                        entity_updates = []

                    models = msg.models_precache
                    server_info_seen = True

                if isinstance(msg, messages.SetViewMessage):
                    view_entity_id = msg.viewentity_id

                if (isinstance(msg, messages.UpdateNameMessage)
                        and view_entity_id is not None
                        and view_entity_id == msg.player_id + 1):
                    name = msg.name
                if (isinstance(msg, messages.UpdateColorsMessage)
                        and view_entity_id is not None
                        and view_entity_id == msg.player_id + 1):
                    color = msg.color

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

        yield cls(models, entity_baseline, entity_updates, times, name, color)

    @classmethod
    def process(cls, dem, base_world_model):
        gis = list(cls.process_all(dem))
        map_gis = [gi for gi in gis if gi.models[1] == base_world_model]
        if len(map_gis) != len(gis):
            bad_maps = [gi.models[1] for gi in gis if gi.models[1] != base_world_model]
            logger.warning(f'ignoring loads on non-base maps: {bad_maps}')
        if not len(map_gis):
            raise Exception(f'ghost demo map(s) ({[gi.models[1] for gi in gis]}) do not match base '
                            f'demo ({base_world_model})')
        if len(map_gis) > 1:
            logger.warning(f"multiple ({len(gis)}) server infos in demos, using longest")
        return max(map_gis, key=lambda gi: len(gi.times))


def _convert_msg_entity(msg, convert_entity_id):
    if isinstance(msg, messages.SpawnBaselineMessage):
        msg = dataclasses.replace(
            msg,
            entity_num=convert_entity_id(msg.entity_num)
        )
    elif isinstance(msg, messages.EntityUpdateMessage):
        msg = dataclasses.replace(
            msg,
            num=convert_entity_id(msg.num)
        )
    elif isinstance(msg, messages.SoundMessage):
        msg = dataclasses.replace(
            msg,
            ent=convert_entity_id(msg.ent)
        )
    elif (isinstance(msg, messages.TempEntityMessage)
          and msg.type == messages.TempEntityType.LIGHTNING4):
        msg = dataclasses.replace(
            msg,
            data=dataclasses.replace(
                msg.data,
                beam=dataclasses.replace(
                    msg.data.beam,
                    entity_num=convert_entity_id(msg.data.beam.entity_num)
                )
            )
        )

    return msg

def _main():
    logging.basicConfig(level=logging.INFO)
    fnames = sys.argv[1:]

    # Parse demos.
    logger.info('parsing base demo')
    base_dem = pydem.parse_demo(fnames[0])
    base_info = _BaseInfo.process(base_dem)
    logger.info('parsing ghost demos')
    ghost_infos = []
    for fname in fnames[1:]:
        logger.info(f"processing {fname}")
        ghost_infos.append(_GhostInfo.process(pydem.parse_demo(fname), base_info.models[1]))

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

    # Construct mappings for entity numbers.
    assert base_info.max_clients <= _MAX_SCOREBOARD
    old_num_clients = base_info.max_clients
    new_num_clients = min(_MAX_SCOREBOARD, old_num_clients + len(ghost_infos))
    def convert_entity_id(entity_id):
        if entity_id < old_num_clients + 1:
            new_entity_id = entity_id
        else:
            new_entity_id = entity_id + new_num_clients - old_num_clients
        return new_entity_id
    ghost_entity_ids = [
        (old_num_clients + 1 + ghost_idx
         if ghost_idx < new_num_clients - old_num_clients
         else (base_info.max_entity_id + 1 + ghost_idx))
        for ghost_idx, ghost_info in enumerate(ghost_infos)
    ]

    # Re-write the original demo.
    new_blocks = []
    for block in base_dem.blocks:
        new_messages = []

        # Convert model numbers to the new numbers.
        last_spawn_baseline_idx = None
        for msg in block.messages:
            if isinstance(msg, (messages.SpawnStaticMessage,
                                messages.SpawnBaselineMessage,
                                messages.EntityUpdateMessage)):
                if msg.modelindex is None:
                    model_num = None
                elif msg.modelindex == 0:
                    model_num = 0
                else:
                    model_num = new_model_dict[
                        base_info.models[msg.modelindex - 1]
                    ]
                if isinstance(msg, messages.SpawnBaselineMessage):
                    last_spawn_baseline_idx = len(new_messages)
                new_messages.append(dataclasses.replace(
                    _convert_msg_entity(msg, convert_entity_id),
                    modelindex=model_num
                ))
            elif isinstance(msg, messages.ServerInfoMessage):
                new_messages.append(
                    dataclasses.replace(msg, max_clients=new_num_clients)
                )
            else:
                new_messages.append(_convert_msg_entity(msg, convert_entity_id))

        # Add baselines onto baseline block.
        if any(isinstance(msg, messages.SpawnBaselineMessage)
                for msg in block.messages):
            for ghost_idx, ghost_info in enumerate(ghost_infos):
                entity_num = ghost_entity_ids[ghost_idx]
                baseline = ghost_info.entity_baseline
                if baseline.modelindex is None:
                    model_num = None
                elif baseline.modelindex == 0:
                    model_num = 0
                else:
                    model_num = new_model_dict[
                        ghost_info.models[baseline.modelindex - 1]
                    ]
                new_messages.insert(
                    last_spawn_baseline_idx,
                    dataclasses.replace(
                        baseline,
                        entity_num=entity_num,
                        modelindex=model_num,
                    )
                )

        # Add name / color updates into sign_on=3 block
        if any(isinstance(msg, messages.SignOnNumMessage) and msg.stage == 3
               for msg in block.messages):
            for ghost_idx, ghost_info in enumerate(ghost_infos):
                entity_num = ghost_entity_ids[ghost_idx]
                if entity_num < new_num_clients + 1:
                    new_messages.extend([
                        messages.UpdateNameMessage(
                            player_id=(entity_num - 1),
                            name=ghost_info.name
                        ),
                        messages.UpdateColorsMessage(
                            player_id=(entity_num - 1),
                            color=ghost_info.color
                        )
                    ])

        # Add update messages.
        if (block.messages
                and isinstance(block.messages[0], messages.TimeMessage)):
            time = block.messages[0].time
            for ghost_idx, ghost_info in enumerate(ghost_infos):

                time_idx = bisect.bisect(ghost_info.times, time) - 1
                if time_idx >= 0:
                    entity_num = ghost_entity_ids[ghost_idx]
                    update = ghost_info.entity_updates[time_idx]
                    if update.modelindex is None:
                        model_num = None
                    elif update.modelindex == 0:
                        model_num = 0
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
