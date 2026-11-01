DELETE FROM media_items_episode WHERE collection_id = :collection_id;

DELETE FROM metadata WHERE parent_table = 'collections' AND parent_id = :collection_id;
