"""Tests for the todo integration."""

import datetime
from typing import Any
import zoneinfo

import pytest
import voluptuous as vol

from homeassistant.components.todo import (
    ATTR_DESCRIPTION,
    ATTR_DUE_DATE,
    ATTR_DUE_DATETIME,
    ATTR_ITEM,
    ATTR_RENAME,
    ATTR_STATUS,
    DOMAIN,
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
    TodoServices,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotSupported,
    ServiceValidationError,
)
from homeassistant.setup import async_setup_component

from . import create_mock_platform

from tests.typing import WebSocketGenerator

ITEM_1 = {
    "uid": "1",
    "summary": "Item #1",
    "status": "needs_action",
}
ITEM_2 = {
    "uid": "2",
    "summary": "Item #2",
    "status": "completed",
}
TEST_TIMEZONE = zoneinfo.ZoneInfo("America/Regina")
TEST_OFFSET = "-06:00"


async def test_unload_entry(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test unloading a config entry with a todo entity."""

    config_entry = await create_mock_platform(hass, [test_entity])
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get("todo.entity1")
    assert state

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED

    state = hass.states.get("todo.entity1")
    assert not state


async def test_list_todo_items(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    test_entity: TodoListEntity,
) -> None:
    """Test listing items in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    state = hass.states.get("todo.entity1")
    assert state
    assert state.state == "1"
    assert state.attributes == {"supported_features": 15}

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "todo/item/list", "entity_id": "todo.entity1"}
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("success")
    assert resp.get("result") == {
        "items": [
            ITEM_1,
            ITEM_2,
        ]
    }


@pytest.mark.parametrize(
    ("service_data", "expected_items"),
    [
        ({}, [ITEM_1, ITEM_2]),
        (
            {ATTR_STATUS: [TodoItemStatus.COMPLETED, TodoItemStatus.NEEDS_ACTION]},
            [ITEM_1, ITEM_2],
        ),
        ({ATTR_STATUS: [TodoItemStatus.NEEDS_ACTION]}, [ITEM_1]),
        ({ATTR_STATUS: [TodoItemStatus.COMPLETED]}, [ITEM_2]),
    ],
)
async def test_get_items_service(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    test_entity: TodoListEntity,
    service_data: dict[str, Any],
    expected_items: list[dict[str, Any]],
) -> None:
    """Test listing items in a To-do list from a service call."""

    await create_mock_platform(hass, [test_entity])

    state = hass.states.get("todo.entity1")
    assert state
    assert state.state == "1"
    assert state.attributes == {ATTR_SUPPORTED_FEATURES: 15}

    result = await hass.services.async_call(
        DOMAIN,
        TodoServices.GET_ITEMS,
        service_data,
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
        return_response=True,
    )
    assert result == {"todo.entity1": {"items": expected_items}}


async def test_unsupported_websocket(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test a To-do list for an entity that does not exist."""

    entity1 = TodoListEntity()
    entity1.entity_id = "todo.entity1"
    await create_mock_platform(hass, [entity1])

    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "todo/item/list",
            "entity_id": "todo.unknown",
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("error", {}).get("code") == "not_found"


@pytest.mark.parametrize(
    ("new_item_name"),
    [
        ("New item"),
        ("New item   "),
        ("  New item"),
    ],
)
async def test_add_item_service(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    new_item_name: str,
) -> None:
    """Test adding an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.ADD_ITEM,
        {ATTR_ITEM: new_item_name},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_create_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid is None
    assert item.summary == "New item"
    assert item.status == TodoItemStatus.NEEDS_ACTION


async def test_add_item_service_raises(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test adding an item in a To-do list that raises an error."""

    await create_mock_platform(hass, [test_entity])

    test_entity.async_create_todo_item.side_effect = HomeAssistantError("Ooops")
    with pytest.raises(HomeAssistantError, match="Ooops"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ITEM: "New item"},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("item_data", "expected_exception", "expected_error"),
    [
        ({}, vol.Invalid, "required key not provided"),
        ({ATTR_ITEM: ""}, vol.Invalid, "length of value must be at least 1"),
        ({ATTR_ITEM: "    "}, vol.Invalid, "length of value must be at least 1"),
        (
            {ATTR_ITEM: "Submit forms", ATTR_DESCRIPTION: "Submit tax forms"},
            ServiceValidationError,
            "does not support setting field: description",
        ),
        (
            {ATTR_ITEM: "Submit forms", ATTR_DUE_DATE: "2023-11-17"},
            ServiceValidationError,
            "does not support setting field: due_date",
        ),
        (
            {
                ATTR_ITEM: "Submit forms",
                ATTR_DUE_DATETIME: f"2023-11-17T17:00:00{TEST_OFFSET}",
            },
            ServiceValidationError,
            "does not support setting field: due_datetime",
        ),
    ],
)
async def test_add_item_service_invalid_input(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    item_data: dict[str, Any],
    expected_exception: str,
    expected_error: str,
) -> None:
    """Test invalid input to the add item service."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(expected_exception) as exc:
        await hass.services.async_call(
            DOMAIN,
            TodoServices.ADD_ITEM,
            item_data,
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )

    assert expected_error in str(exc.value)


@pytest.mark.parametrize(
    ("supported_entity_feature", "item_data", "expected_item"),
    [
        (
            TodoListEntityFeature.SET_DUE_DATE_ON_ITEM,
            {ATTR_ITEM: "New item", ATTR_DUE_DATE: "2023-11-13"},
            TodoItem(
                summary="New item",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.date(2023, 11, 13),
            ),
        ),
        (
            TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM,
            {
                ATTR_ITEM: "New item",
                ATTR_DUE_DATETIME: f"2023-11-13T17:00:00{TEST_OFFSET}",
            },
            TodoItem(
                summary="New item",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.datetime(2023, 11, 13, 17, 00, 00, tzinfo=TEST_TIMEZONE),
            ),
        ),
        (
            TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM,
            {ATTR_ITEM: "New item", ATTR_DUE_DATETIME: "2023-11-13T17:00:00+00:00"},
            TodoItem(
                summary="New item",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.datetime(2023, 11, 13, 11, 00, 00, tzinfo=TEST_TIMEZONE),
            ),
        ),
        (
            TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM,
            {ATTR_ITEM: "New item", ATTR_DUE_DATETIME: "2023-11-13"},
            TodoItem(
                summary="New item",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.datetime(2023, 11, 13, 0, 00, 00, tzinfo=TEST_TIMEZONE),
            ),
        ),
        (
            TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM,
            {ATTR_ITEM: "New item", ATTR_DESCRIPTION: "Submit revised draft"},
            TodoItem(
                summary="New item",
                status=TodoItemStatus.NEEDS_ACTION,
                description="Submit revised draft",
            ),
        ),
    ],
)
async def test_add_item_service_extended_fields(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    supported_entity_feature: int,
    item_data: dict[str, Any],
    expected_item: TodoItem,
) -> None:
    """Test adding an item in a To-do list."""

    test_entity._attr_supported_features |= supported_entity_feature
    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.ADD_ITEM,
        {ATTR_ITEM: "New item", **item_data},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_create_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item == expected_item


@pytest.mark.parametrize(
    ("new_item_name"),
    [
        ("Updated item"),
        ("Updated item  "),
        ("  Updated item "),
    ],
)
async def test_update_todo_item_service_by_id(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    new_item_name: str,
) -> None:
    """Test updating an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", ATTR_RENAME: new_item_name, ATTR_STATUS: "completed"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid == "1"
    assert item.summary == "Updated item"
    assert item.status == TodoItemStatus.COMPLETED


async def test_update_todo_item_service_by_id_status_only(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", ATTR_STATUS: "completed"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid == "1"
    assert item.summary == "Item #1"
    assert item.status == TodoItemStatus.COMPLETED


async def test_update_todo_item_service_by_id_rename(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", "rename": "Updated item"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid == "1"
    assert item.summary == "Updated item"
    assert item.status == TodoItemStatus.NEEDS_ACTION


async def test_update_todo_item_service_raises(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list that raises an error."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", "rename": "Updated item", "status": "completed"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    test_entity.async_update_todo_item.side_effect = HomeAssistantError("Ooops")
    with pytest.raises(HomeAssistantError, match="Ooops"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.UPDATE_ITEM,
            {ATTR_ITEM: "1", "rename": "Updated item", "status": "completed"},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_update_todo_item_service_by_summary(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list by summary."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "Item #1", "rename": "Something else", "status": "completed"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid == "1"
    assert item.summary == "Something else"
    assert item.status == TodoItemStatus.COMPLETED


async def test_update_todo_item_service_by_summary_only_status(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list by summary."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "Item #1", "rename": "Something else"},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item
    assert item.uid == "1"
    assert item.summary == "Something else"
    assert item.status == TodoItemStatus.NEEDS_ACTION


async def test_update_todo_item_service_by_summary_not_found(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test updating an item in a To-do list by summary which is not found."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(ServiceValidationError, match="Unable to find"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.UPDATE_ITEM,
            {ATTR_ITEM: "Item #7", "status": "completed"},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("item_data", "expected_error"),
    [
        ({}, r"required key not provided @ data\['item'\]"),
        ({"status": "needs_action"}, r"required key not provided @ data\['item'\]"),
        ({"item": "Item #1"}, "must contain at least one of"),
        (
            {"item": "", "status": "needs_action"},
            "length of value must be at least 1",
        ),
    ],
)
async def test_update_item_service_invalid_input(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    item_data: dict[str, Any],
    expected_error: str,
) -> None:
    """Test invalid input to the update item service."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(vol.Invalid, match=expected_error):
        await hass.services.async_call(
            DOMAIN,
            "update_item",
            item_data,
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("update_data"),
    [
        ({"due_datetime": f"2023-11-13T17:00:00{TEST_OFFSET}"}),
        ({"due_date": "2023-11-13"}),
        ({"description": "Submit revised draft"}),
    ],
)
async def test_update_todo_item_field_unsupported(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    update_data: dict[str, Any],
) -> None:
    """Test updating an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(ServiceValidationError, match="does not support"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.UPDATE_ITEM,
            {ATTR_ITEM: "1", **update_data},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("supported_entity_feature", "update_data", "expected_update"),
    [
        (
            TodoListEntityFeature.SET_DUE_DATE_ON_ITEM,
            {"due_date": "2023-11-13"},
            TodoItem(
                uid="1",
                summary="Item #1",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.date(2023, 11, 13),
            ),
        ),
        (
            TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM,
            {"due_datetime": f"2023-11-13T17:00:00{TEST_OFFSET}"},
            TodoItem(
                uid="1",
                summary="Item #1",
                status=TodoItemStatus.NEEDS_ACTION,
                due=datetime.datetime(2023, 11, 13, 17, 0, 0, tzinfo=TEST_TIMEZONE),
            ),
        ),
        (
            TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM,
            {"description": "Submit revised draft"},
            TodoItem(
                uid="1",
                summary="Item #1",
                status=TodoItemStatus.NEEDS_ACTION,
                description="Submit revised draft",
            ),
        ),
    ],
)
async def test_update_todo_item_extended_fields(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    supported_entity_feature: int,
    update_data: dict[str, Any],
    expected_update: TodoItem,
) -> None:
    """Test updating an item in a To-do list."""

    test_entity._attr_supported_features |= supported_entity_feature
    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", **update_data},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item == expected_update


@pytest.mark.parametrize(
    ("test_entity_items", "update_data", "expected_update"),
    [
        (
            [TodoItem(uid="1", summary="Summary", description="description")],
            {"description": "Submit revised draft"},
            TodoItem(uid="1", summary="Summary", description="Submit revised draft"),
        ),
        (
            [TodoItem(uid="1", summary="Summary", description="description")],
            {"description": ""},
            TodoItem(uid="1", summary="Summary", description=""),
        ),
        (
            [TodoItem(uid="1", summary="Summary", description="description")],
            {"description": None},
            TodoItem(uid="1", summary="Summary"),
        ),
        (
            [TodoItem(uid="1", summary="Summary", due=datetime.date(2024, 1, 1))],
            {"due_date": datetime.date(2024, 1, 2)},
            TodoItem(uid="1", summary="Summary", due=datetime.date(2024, 1, 2)),
        ),
        (
            [TodoItem(uid="1", summary="Summary", due=datetime.date(2024, 1, 1))],
            {"due_date": None},
            TodoItem(uid="1", summary="Summary"),
        ),
        (
            [TodoItem(uid="1", summary="Summary", due=datetime.date(2024, 1, 1))],
            {"due_datetime": datetime.datetime(2024, 1, 1, 10, 0, 0)},
            TodoItem(
                uid="1",
                summary="Summary",
                due=datetime.datetime(
                    2024, 1, 1, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo(key="America/Regina")
                ),
            ),
        ),
        (
            [
                TodoItem(
                    uid="1",
                    summary="Summary",
                    due=datetime.datetime(2024, 1, 1, 10, 0, 0),
                )
            ],
            {"due_datetime": None},
            TodoItem(uid="1", summary="Summary"),
        ),
    ],
    ids=[
        "overwrite_description",
        "overwrite_empty_description",
        "clear_description",
        "overwrite_due_date",
        "clear_due_date",
        "overwrite_due_date_with_time",
        "clear_due_date_time",
    ],
)
async def test_update_todo_item_extended_fields_overwrite_existing_values(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    update_data: dict[str, Any],
    expected_update: TodoItem,
) -> None:
    """Test updating an item in a To-do list."""

    test_entity._attr_supported_features |= (
        TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
    )
    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ITEM: "1", **update_data},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_update_todo_item.call_args
    assert args
    item = args.kwargs.get("item")
    assert item == expected_update


async def test_remove_todo_item_service_by_id(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test removing an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.REMOVE_ITEM,
        {ATTR_ITEM: ["1", "2"]},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_delete_todo_items.call_args
    assert args
    assert args.kwargs.get("uids") == ["1", "2"]


async def test_remove_todo_item_service_raises(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test removing an item in a To-do list that raises an error."""

    await create_mock_platform(hass, [test_entity])

    test_entity.async_delete_todo_items.side_effect = HomeAssistantError("Ooops")
    with pytest.raises(HomeAssistantError, match="Ooops"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.REMOVE_ITEM,
            {ATTR_ITEM: ["1", "2"]},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_remove_todo_item_service_invalid_input(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test invalid input to the remove item service."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(
        vol.Invalid, match=r"required key not provided @ data\['item'\]"
    ):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.REMOVE_ITEM,
            {},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_remove_todo_item_service_by_summary(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test removing an item in a To-do list by summary."""

    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.REMOVE_ITEM,
        {ATTR_ITEM: ["Item #1"]},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_delete_todo_items.call_args
    assert args
    assert args.kwargs.get("uids") == ["1"]


async def test_remove_todo_item_service_by_summary_not_found(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test removing an item in a To-do list by summary which is not found."""

    await create_mock_platform(hass, [test_entity])

    with pytest.raises(ServiceValidationError, match="Unable to find"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.REMOVE_ITEM,
            {ATTR_ITEM: ["Item #7"]},
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_move_todo_item_service_by_id(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test moving an item in a To-do list."""

    await create_mock_platform(hass, [test_entity])

    client = await hass_ws_client()
    await client.send_json(
        {
            "id": 1,
            "type": "todo/item/move",
            "entity_id": "todo.entity1",
            "uid": "item-1",
            "previous_uid": "item-2",
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("success")

    args = test_entity.async_move_todo_item.call_args
    assert args
    assert args.kwargs.get("uid") == "item-1"
    assert args.kwargs.get("previous_uid") == "item-2"


async def test_move_todo_item_service_raises(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test moving an item in a To-do list that raises an error."""

    await create_mock_platform(hass, [test_entity])

    test_entity.async_move_todo_item.side_effect = HomeAssistantError("Ooops")
    client = await hass_ws_client()
    await client.send_json(
        {
            "id": 1,
            "type": "todo/item/move",
            "entity_id": "todo.entity1",
            "uid": "item-1",
            "previous_uid": "item-2",
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("error", {}).get("code") == "failed"
    assert resp.get("error", {}).get("message") == "Ooops"


@pytest.mark.parametrize(
    ("item_data", "expected_status", "expected_error"),
    [
        (
            {"entity_id": "todo.unknown", "uid": "item-1"},
            "not_found",
            "Entity not found",
        ),
        ({"entity_id": "todo.entity1"}, "invalid_format", "required key not provided"),
        (
            {"entity_id": "todo.entity1", "previous_uid": "item-2"},
            "invalid_format",
            "required key not provided",
        ),
    ],
)
async def test_move_todo_item_service_invalid_input(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
    hass_ws_client: WebSocketGenerator,
    item_data: dict[str, Any],
    expected_status: str,
    expected_error: str,
) -> None:
    """Test invalid input for the move item service."""

    await create_mock_platform(hass, [test_entity])

    client = await hass_ws_client()
    await client.send_json(
        {
            "id": 1,
            "type": "todo/item/move",
            **item_data,
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("error", {}).get("code") == expected_status
    assert expected_error in resp.get("error", {}).get("message")


@pytest.mark.parametrize(
    ("service_name", "payload"),
    [
        (
            TodoServices.ADD_ITEM,
            {
                ATTR_ITEM: "New item",
            },
        ),
        (
            TodoServices.REMOVE_ITEM,
            {
                ATTR_ITEM: ["1"],
            },
        ),
        (
            TodoServices.UPDATE_ITEM,
            {
                ATTR_ITEM: "1",
                ATTR_RENAME: "Updated item",
            },
        ),
        (
            TodoServices.REMOVE_COMPLETED_ITEMS,
            None,
        ),
    ],
)
async def test_unsupported_service(
    hass: HomeAssistant,
    service_name: str,
    payload: dict[str, Any] | None,
) -> None:
    """Test a To-do list that does not support features."""
    # Fetch translations
    await async_setup_component(hass, "homeassistant", "")
    entity1 = TodoListEntity()
    entity1.entity_id = "todo.entity1"
    await create_mock_platform(hass, [entity1])

    with pytest.raises(
        ServiceNotSupported,
        match=f"Entity todo.entity1 does not support action {DOMAIN}.{service_name}",
    ):
        await hass.services.async_call(
            DOMAIN,
            service_name,
            payload,
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_move_item_unsupported(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test invalid input for the move item service."""

    entity1 = TodoListEntity()
    entity1.entity_id = "todo.entity1"
    await create_mock_platform(hass, [entity1])

    client = await hass_ws_client()
    await client.send_json(
        {
            "id": 1,
            "type": "todo/item/move",
            "entity_id": "todo.entity1",
            "uid": "item-1",
            "previous_uid": "item-2",
        }
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("error", {}).get("code") == "not_supported"


async def test_remove_completed_items_service(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test remove completed todo items service."""
    await create_mock_platform(hass, [test_entity])

    await hass.services.async_call(
        DOMAIN,
        TodoServices.REMOVE_COMPLETED_ITEMS,
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )

    args = test_entity.async_delete_todo_items.call_args
    assert args
    assert args.kwargs.get("uids") == ["2"]

    test_entity.async_delete_todo_items.reset_mock()

    # calling service multiple times will not call the entity method
    await hass.services.async_call(
        DOMAIN,
        TodoServices.REMOVE_COMPLETED_ITEMS,
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
    )
    test_entity.async_delete_todo_items.assert_not_called()


async def test_remove_completed_items_service_raises(
    hass: HomeAssistant,
    test_entity: TodoListEntity,
) -> None:
    """Test removing all completed item from a To-do list that raises an error."""

    await create_mock_platform(hass, [test_entity])

    test_entity.async_delete_todo_items.side_effect = HomeAssistantError("Ooops")
    with pytest.raises(HomeAssistantError, match="Ooops"):
        await hass.services.async_call(
            DOMAIN,
            TodoServices.REMOVE_COMPLETED_ITEMS,
            target={ATTR_ENTITY_ID: "todo.entity1"},
            blocking=True,
        )


async def test_subscribe(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    test_entity: TodoListEntity,
) -> None:
    """Test subscribing to todo updates."""

    await create_mock_platform(hass, [test_entity])

    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "todo/item/subscribe",
            "entity_id": test_entity.entity_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] is None
    subscription_id = msg["id"]

    msg = await client.receive_json()
    assert msg["id"] == subscription_id
    assert msg["type"] == "event"
    event_message = msg["event"]
    assert event_message == {
        "items": [
            {
                "summary": "Item #1",
                "uid": "1",
                "status": "needs_action",
                "due": None,
                "description": None,
            },
            {
                "summary": "Item #2",
                "uid": "2",
                "status": "completed",
                "due": None,
                "description": None,
            },
        ]
    }
    test_entity._attr_todo_items = [
        *test_entity._attr_todo_items,
        TodoItem(summary="Item #3", uid="3", status=TodoItemStatus.NEEDS_ACTION),
    ]

    test_entity.async_write_ha_state()
    msg = await client.receive_json()
    event_message = msg["event"]
    assert event_message == {
        "items": [
            {
                "summary": "Item #1",
                "uid": "1",
                "status": "needs_action",
                "due": None,
                "description": None,
            },
            {
                "summary": "Item #2",
                "uid": "2",
                "status": "completed",
                "due": None,
                "description": None,
            },
            {
                "summary": "Item #3",
                "uid": "3",
                "status": "needs_action",
                "due": None,
                "description": None,
            },
        ]
    }

    test_entity._attr_todo_items = None
    test_entity.async_write_ha_state()
    msg = await client.receive_json()
    event_message = msg["event"]
    assert event_message == {
        "items": [],
    }


async def test_subscribe_entity_does_not_exist(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    test_entity: TodoListEntity,
) -> None:
    """Test failure to subscribe to an entity that does not exist."""

    await create_mock_platform(hass, [test_entity])

    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "todo/item/subscribe",
            "entity_id": "todo.unknown",
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {
        "code": "invalid_entity_id",
        "message": "To-do list entity not found: todo.unknown",
    }


@pytest.mark.parametrize(
    ("item_data", "expected_item_data"),
    [
        ({"due": datetime.date(2023, 11, 17)}, {"due": "2023-11-17"}),
        (
            {"due": datetime.datetime(2023, 11, 17, 17, 0, 0, tzinfo=TEST_TIMEZONE)},
            {"due": f"2023-11-17T17:00:00{TEST_OFFSET}"},
        ),
        ({"description": "Some description"}, {"description": "Some description"}),
    ],
)
async def test_list_todo_items_extended_fields(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    test_entity: TodoListEntity,
    item_data: dict[str, Any],
    expected_item_data: dict[str, Any],
) -> None:
    """Test listing items in a To-do list with extended fields."""

    test_entity._attr_todo_items = [
        TodoItem(
            **ITEM_1,
            **item_data,
        ),
    ]
    await create_mock_platform(hass, [test_entity])

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "todo/item/list", "entity_id": "todo.entity1"}
    )
    resp = await client.receive_json()
    assert resp.get("id") == 1
    assert resp.get("success")
    assert resp.get("result") == {
        "items": [
            {
                **ITEM_1,
                **expected_item_data,
            },
        ]
    }

    result = await hass.services.async_call(
        DOMAIN,
        "get_items",
        {},
        target={ATTR_ENTITY_ID: "todo.entity1"},
        blocking=True,
        return_response=True,
    )
    assert result == {
        "todo.entity1": {
            "items": [
                {
                    **ITEM_1,
                    **expected_item_data,
                },
            ]
        }
    }
